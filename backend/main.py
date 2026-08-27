"""
WebGuardian AI - Phase 1 Backend
=================================
FastAPI app exposing the autonomous scan pipeline.

Phase 1 uses an in-memory store (SCANS dict) so the whole thing runs with
zero external dependencies beyond Playwright. Phase 2/3 swap this for
PostgreSQL without changing the API surface - every scan is already a
plain dict (state.to_dict()), so persisting it later is a drop-in change.

Run:
    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations
import asyncio
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.agents.state import ScanState
from backend.agents.supervisor import run_scan

app = FastAPI(title="WebGuardian AI", version="0.1.0-phase1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

import json

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "storage")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(os.path.join(STORAGE_DIR, "screenshots"), exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STORAGE_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# In-memory scan store: scan_id -> ScanState
SCANS: dict[str, ScanState] = {}


def _generate_html_report(report_data: dict) -> str:
    import html
    url = html.escape(str(report_data.get("website_url", "")))
    scan_id = html.escape(str(report_data.get("scan_id", "")))
    finished = html.escape(str(report_data.get("finished_at", report_data.get("started_at", ""))))
    score = report_data.get("quality_score") or {}
    bugs = report_data.get("bugs") or []

    bugs_rows = []
    for b in bugs:
        sev = html.escape(str(b.get("severity", "LOW")).upper())
        title = html.escape(str(b.get("title", "Untitled Bug")))
        cat = html.escape(str(b.get("category", "general")))
        page = html.escape(str(b.get("page_url", b.get("page", ""))))
        rc = html.escape(str(b.get("root_cause", b.get("severity_rationale", ""))))
        v_status = b.get("verification_status", "still_present")
        v_badge = '<span style="color:#f85149; background:rgba(248,81,73,.15); padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;">Still Present</span>' if v_status == "still_present" else '<span style="color:#3fb950; background:rgba(63,185,80,.15); padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;">Not Reproducible</span>'
        
        fix_rec = b.get("fix_recommendation")
        if isinstance(fix_rec, dict):
            what = html.escape(str(fix_rec.get("what", b.get("suggested_fix", ""))))
            where = html.escape(str(fix_rec.get("where", page)))
            impact = html.escape(str(fix_rec.get("expected_impact", "")))
            fix_html = f'''
            <div style="background:#0d1218; border-left:3px solid #3fb950; padding:8px 12px; margin-top:6px; border-radius:0 4px 4px 0;">
                <div style="color:#3fb950; font-weight:bold;">💡 Recommended Fix: {what}</div>
                <div style="font-size:11px; color:#8a99ad; margin-top:2px;">📍 <strong>Where:</strong> {where}</div>
                <div style="font-size:11px; color:#8a99ad; margin-top:2px;">🎯 <strong>Expected Impact:</strong> {impact}</div>
            </div>
            '''
        else:
            fix_text = html.escape(str(b.get("suggested_fix", "Remediate according to web QA guidelines.")))
            fix_html = f'<div style="background:#0d1218; border-left:3px solid #3fb950; padding:8px 12px; margin-top:6px; border-radius:0 4px 4px 0;"><strong>Suggested Fix:</strong> {fix_text}</div>'

        bugs_rows.append(f'''
        <tr>
            <td style="padding:12px; border-bottom:1px solid #1e2632;">
                <span style="padding:2px 8px; border-radius:20px; font-size:10px; font-weight:bold; background:rgba(45,212,191,0.1); color:#2dd4bf;">{sev}</span>
                <div style="margin-top:6px;">{v_badge}</div>
            </td>
            <td style="padding:12px; border-bottom:1px solid #1e2632;">
                <strong style="color:#e2e8f0; display:block;">{title}</strong>
                <span style="display:inline-block; padding:2px 6px; border-radius:4px; font-size:10px; background:#0d1218; border:1px solid #1e2632; color:#8a99ad; margin-top:4px;">{cat}</span>
            </td>
            <td style="padding:12px; border-bottom:1px solid #1e2632; font-family:monospace; font-size:11px; color:#2dd4bf; word-break:break-all;">
                {page}
            </td>
            <td style="padding:12px; border-bottom:1px solid #1e2632;">
                <div style="background:#0d1218; border-left:3px solid #2dd4bf; padding:8px 12px; border-radius:0 4px 4px 0; font-size:12px;"><strong>Root Cause:</strong> {rc}</div>
                {fix_html}
            </td>
        </tr>
        ''')

    bugs_table_html = "".join(bugs_rows) if bugs_rows else '<tr><td colspan="4" style="padding:16px; text-align:center; color:#8a99ad;">No bugs detected.</td></tr>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>WebGuardian AI Scan Report - {url}</title>
<style>
    body {{ background: #090d12; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 24px; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}
    .header {{ border-bottom: 1px solid #1e2632; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }}
    h1 {{ font-size: 22px; color: #2dd4bf; margin: 0; }}
    .meta {{ font-size: 12px; color: #8a99ad; margin-top: 4px; }}
    .panel {{ background: #121820; border: 1px solid #1e2632; border-radius: 10px; padding: 20px; margin-bottom: 24px; }}
    .panel h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #8a99ad; margin-top: 0; margin-bottom: 16px; }}
    .grid {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .card {{ flex: 1; min-width: 120px; background: #0d1218; border: 1px solid #1e2632; border-radius: 8px; padding: 14px; text-align: center; }}
    .card .num {{ font-size: 26px; font-weight: bold; color: #2dd4bf; }}
    .card .lbl {{ font-size: 10px; color: #8a99ad; text-transform: uppercase; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th {{ text-align: left; color: #8a99ad; text-transform: uppercase; font-size: 10px; padding: 10px; border-bottom: 1px solid #1e2632; }}
    .notice {{ background: rgba(210, 153, 34, 0.15); border: 1px solid rgba(210, 153, 34, 0.4); color: #e3b341; padding: 10px 16px; border-radius: 6px; font-size: 12px; margin-bottom: 16px; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>WebGuardian AI — Autonomous Scan Report</h1>
            <div class="meta">Target: <strong>{url}</strong> | Scan ID: <code>{scan_id}</code> | Completed: {finished}</div>
        </div>
    </div>

    <div class="panel">
        <h2>Quality Scoreboard</h2>
        <div class="grid">
            <div class="card"><div class="num">{score.get('overall', '-')}</div><div class="lbl">Overall Score</div></div>
            <div class="card"><div class="num">{score.get('functional', '-')}</div><div class="lbl">Functional</div></div>
            <div class="card"><div class="num">{score.get('accessibility', '-')}</div><div class="lbl">Accessibility</div></div>
            <div class="card"><div class="num">{score.get('visual', '-')}</div><div class="lbl">Visual</div></div>
            <div class="card"><div class="num">{score.get('performance', '-')}</div><div class="lbl">Performance</div></div>
            <div class="card"><div class="num">{score.get('security', '-')}</div><div class="lbl">Security</div></div>
            <div class="card"><div class="num">{score.get('bugs_found', len(bugs))}</div><div class="lbl">Bugs Found</div></div>
        </div>
    </div>

    <div class="panel">
        <h2>Bug Intelligence Explorer</h2>
        <div class="notice">⚠️ AI-Recommended Fix (Not Auto-Applied) — Fixes are generated recommendations for developer remediation.</div>
        <table>
            <thead>
                <tr>
                    <th style="width:130px">Severity & Status</th>
                    <th style="width:220px">Title / Category</th>
                    <th style="width:180px">Page URL</th>
                    <th>Root Cause & Actionable Fix Recommendation</th>
                </tr>
            </thead>
            <tbody>
                {bugs_table_html}
            </tbody>
        </table>
    </div>
</div>
</body>
</html>'''


@app.get("/api/scan/{scan_id}/export")
async def export_scan_report(scan_id: str):
    state = _get_scan(scan_id)
    report_data = state.to_dict()
    report_data["rag_enabled"] = True
    report_data["llm_configured"] = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # Save JSON report file
    json_filename = f"report_{scan_id}.json"
    json_filepath = os.path.join(REPORTS_DIR, json_filename)
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    # Save HTML summary report file
    html_filename = f"report_{scan_id}.html"
    html_filepath = os.path.join(REPORTS_DIR, html_filename)
    html_content = _generate_html_report(report_data)
    with open(html_filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    return {
        "status": "success",
        "scan_id": scan_id,
        "json_file": json_filename,
        "html_file": html_filename,
        "json_url": f"/reports/{json_filename}",
        "html_url": f"/reports/{html_filename}",
        "report_data": report_data,
    }


class ScanRequest(BaseModel):
    url: str
    max_pages: int = Field(default=10, ge=1, le=50)
    max_depth: int = Field(default=2, ge=0, le=5)
    device: str = Field(default="desktop", pattern="^(desktop|mobile|tablet)$")


class ScanResponse(BaseModel):
    scan_id: str
    scan_status: str


@app.get("/health")
@app.get("/api/health")
async def health():
    playwright_ok = True
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        playwright_ok = False
    return {
        "backend": "running",
        "browser_available": playwright_ok,
        "database": "in-memory",
        "llm_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "rag_available": True,
    }


@app.post("/api/scan", response_model=ScanResponse)
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    state = ScanState(
        website_url=req.url,
        max_pages=req.max_pages,
        max_depth=req.max_depth,
        device=req.device,
    )
    SCANS[state.scan_id] = state

    async def _run():
        dynamic_timeout = min(300, max(60, 60 + req.max_pages * 30))
        try:
            await asyncio.wait_for(run_scan(state), timeout=dynamic_timeout)
        except asyncio.TimeoutError:
            state.scan_status = "failed"
            state.error = f"Scan overall timeout exceeded ({dynamic_timeout}s limit)"
            state.log("Supervisor", "Scan timed out", "failed", f"Exceeded {dynamic_timeout}s overall timeout")
        except Exception as e:  # last-resort safety net so the task never silently dies
            state.scan_status = "failed"
            state.error = str(e)
            state.log("Supervisor", "Unhandled exception during scan", "failed", str(e))

    background_tasks.add_task(_run)
    return ScanResponse(scan_id=state.scan_id, scan_status=state.scan_status)


def _get_scan(scan_id: str) -> ScanState:
    state = SCANS.get(scan_id)
    if not state:
        raise HTTPException(status_code=404, detail="Scan not found")
    return state


@app.get("/api/scan/{scan_id}")
async def get_scan(scan_id: str):
    data = _get_scan(scan_id).to_dict()
    data["rag_enabled"] = True
    data["llm_configured"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return data


@app.get("/api/scan/{scan_id}/status")
async def get_scan_status(scan_id: str):
    state = _get_scan(scan_id)
    return {
        "scan_id": state.scan_id,
        "scan_status": state.scan_status,
        "current_agent": state.current_agent,
        "error": state.error,
        "pages_scanned": len(state.pages),
    }


@app.get("/api/scan/{scan_id}/agents")
async def get_scan_agents(scan_id: str):
    return {"agent_log": _get_scan(scan_id).agent_log}


@app.get("/api/scan/{scan_id}/bugs")
async def get_scan_bugs(scan_id: str):
    return {"bugs": _get_scan(scan_id).bugs}


@app.get("/api/scan/{scan_id}/screenshots")
async def get_scan_screenshots(scan_id: str):
    state = _get_scan(scan_id)
    return {
        "screenshots": [
            {**s, "url_path": f"/static/screenshots/{os.path.basename(s['path'])}"} for s in state.screenshots
        ]
    }


@app.get("/api/scan/{scan_id}/report")
async def get_scan_report(scan_id: str):
    state = _get_scan(scan_id)
    return {
        "website_url": state.website_url,
        "scan_status": state.scan_status,
        "quality_score": state.quality_score,
        "pages_scanned": len(state.pages),
        "tests_generated": len(state.functional_tests),
        "bugs": state.bugs,
        "accessibility_findings": state.accessibility_findings,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
    }
