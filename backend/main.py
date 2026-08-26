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

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "storage")
os.makedirs(os.path.join(STORAGE_DIR, "screenshots"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STORAGE_DIR), name="static")

# In-memory scan store: scan_id -> ScanState
SCANS: dict[str, ScanState] = {}


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
        "database": "in-memory (phase 1)",
        "llm_configured": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")),
        "rag_available": False,  # arrives in phase 2
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
        try:
            await run_scan(state)
        except Exception as e:  # last-resort safety net so the task never silently dies
            state.scan_status = "failed"
            state.error = str(e)
            state.log("Supervisor", "Unhandled exception during scan", "failed", str(e))

    background_tasks.add_task(lambda: asyncio.create_task(_run()))
    return ScanResponse(scan_id=state.scan_id, scan_status=state.scan_status)


def _get_scan(scan_id: str) -> ScanState:
    state = SCANS.get(scan_id)
    if not state:
        raise HTTPException(status_code=404, detail="Scan not found")
    return state


@app.get("/api/scan/{scan_id}")
async def get_scan(scan_id: str):
    return _get_scan(scan_id).to_dict()


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
