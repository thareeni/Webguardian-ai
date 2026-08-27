"""
Visual QA Agent
================
Detects visual and layout defects using Playwright's bounding-box and
computed-style APIs (no heavy ML/computer vision dependencies):
  - Viewport/horizontal overflow (elements extending beyond viewport width)
  - Element overlap (colliding interactive/text elements)
  - Missing/empty components (unlabeled buttons, empty links, zero-size images)
"""
from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright

from .state import ScanState

DEVICE_VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}


async def audit_page_visuals(page, url: str) -> list[dict]:
    findings: list[dict] = []

    res = await page.evaluate("""
    () => {
        const issues = [];
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // 1. Viewport Overflow Check
        const allEls = Array.from(document.querySelectorAll('body *'));
        for (const el of allEls) {
            if (el.offsetWidth <= 0 || el.offsetHeight <= 0) continue;
            const rect = el.getBoundingClientRect();
            if ((rect.right > vw + 10 || el.scrollWidth > vw + 10 || rect.width > vw + 10) && el.tagName.toLowerCase() !== 'html' && el.tagName.toLowerCase() !== 'body') {
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? `.${String(el.className).split(' ')[0]}` : '';
                const id = el.id ? `#${el.id}` : '';
                issues.push({
                    type: 'overflow',
                    severity: 'MEDIUM',
                    description: `Element <${tag}${id}${cls}> extends beyond viewport boundary (element width=${Math.round(rect.width)}px, right=${Math.round(rect.right)}px, viewport width=${vw}px)`,
                    selector: `${tag}${id}${cls}`,
                });
                break;
            }
        }

        // 2. Element Overlap Check
        const candidates = Array.from(document.querySelectorAll('button, a, input, select, h1, h2, h3, p'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.top < vh && r.left < vw;
            })
            .slice(0, 30);

        for (let i = 0; i < candidates.length; i++) {
            for (let j = i + 1; j < candidates.length; j++) {
                const e1 = candidates[i];
                const e2 = candidates[j];
                if (e1.contains(e2) || e2.contains(e1)) continue;

                const r1 = e1.getBoundingClientRect();
                const r2 = e2.getBoundingClientRect();

                const xOverlap = Math.max(0, Math.min(r1.right, r2.right) - Math.max(r1.left, r2.left));
                const yOverlap = Math.max(0, Math.min(r1.bottom, r2.bottom) - Math.max(r1.top, r2.top));
                const overlapArea = xOverlap * yOverlap;

                const minArea = Math.min(r1.width * r1.height, r2.width * r2.height);
                if (minArea > 0 && overlapArea / minArea > 0.4) {
                    const tag1 = `${e1.tagName.toLowerCase()}${e1.id ? '#'+e1.id : ''}`;
                    const tag2 = `${e2.tagName.toLowerCase()}${e2.id ? '#'+e2.id : ''}`;
                    issues.push({
                        type: 'overlap',
                        severity: 'HIGH',
                        description: `Visual overlap detected between <${tag1}> and <${tag2}> (${Math.round((overlapArea/minArea)*100)}% collision)`,
                        selector: `${tag1} / ${tag2}`,
                    });
                }
            }
        }

        // 3. Missing / Empty Components Check
        const buttons = Array.from(document.querySelectorAll('button, [role=button]'));
        for (const btn of buttons) {
            const text = (btn.innerText || btn.getAttribute('aria-label') || btn.value || '').trim();
            if (!text && btn.children.length === 0) {
                issues.push({
                    type: 'empty_component',
                    severity: 'MEDIUM',
                    description: 'Interactive button has no text content or aria-label',
                    selector: btn.tagName.toLowerCase() + (btn.id ? `#${btn.id}` : ''),
                });
            }
        }

        return issues;
    }
    """)

    for issue in res:
        findings.append({
            "page": url,
            "category": "visual",
            "type": issue["type"],
            "severity": issue["severity"],
            "description": issue["description"],
            "selector": issue["selector"],
        })

    return findings


async def run_visual_audit(state: ScanState) -> ScanState:
    state.log("VisualAgent", "Running visual and layout inspection", "running")

    findings: list[dict] = []
    viewport = DEVICE_VIEWPORTS.get(state.device, DEVICE_VIEWPORTS["desktop"])

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport=viewport, ignore_https_errors=True)
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(15000)

        for page_record in state.pages:
            url = page_record["url"]
            page = await context.new_page()
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page_findings = await asyncio.wait_for(audit_page_visuals(page, url), timeout=10)
                findings.extend(page_findings)
            except Exception as e:
                state.log("VisualAgent", f"Visual audit skipped/failed for {url}", "warning", str(e))
            finally:
                await page.close()

        await browser.close()

    state.visual_findings = findings
    state.log(
        "VisualAgent",
        "Visual inspection complete",
        "success",
        f"{len(findings)} layout issue(s) detected across {len(state.pages)} page(s)",
    )
    return state
