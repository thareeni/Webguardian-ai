"""
Accessibility Agent
====================
Injects axe-core (industry-standard accessibility engine) into every
discovered page and runs a full audit. This is real tool usage, not a
hand-rolled heuristic - axe-core decides what violates WCAG, this agent
just orchestrates it and folds the results into shared state.
"""
from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright

from .state import ScanState

AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
AXE_SCRIPT_CONTENT: str | None = None


def _get_axe_script() -> str | None:
    global AXE_SCRIPT_CONTENT
    if AXE_SCRIPT_CONTENT is None:
        try:
            import urllib.request
            AXE_SCRIPT_CONTENT = urllib.request.urlopen(AXE_CDN, timeout=8).read().decode("utf-8")
        except Exception:
            AXE_SCRIPT_CONTENT = ""
    return AXE_SCRIPT_CONTENT or None


async def run_accessibility_audit(state: ScanState) -> ScanState:
    state.log("AccessibilityAgent", "Running axe-core audits", "running")

    findings: list[dict] = []
    viewport = {"width": 1440, "height": 900}

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

                async def _run_axe():
                    script = _get_axe_script()
                    if script:
                        await page.add_script_tag(content=script)
                    else:
                        await page.add_script_tag(url=AXE_CDN)
                    return await page.evaluate(
                        "async () => await axe.run(document, {resultTypes: ['violations']})"
                    )

                axe_results = await asyncio.wait_for(_run_axe(), timeout=12)
                for v in axe_results.get("violations", []):
                    findings.append(
                        {
                            "page": url,
                            "rule_id": v.get("id"),
                            "impact": v.get("impact"),  # minor|moderate|serious|critical
                            "description": v.get("description"),
                            "help": v.get("help"),
                            "help_url": v.get("helpUrl"),
                            "nodes_affected": len(v.get("nodes", [])),
                            "example_selector": (
                                v["nodes"][0]["target"][0] if v.get("nodes") else None
                            ),
                        }
                    )
            except Exception as e:
                state.log("AccessibilityAgent", f"Audit failed for {url}", "warning", str(e))
            finally:
                await page.close()

        await browser.close()

    state.accessibility_findings = findings
    by_impact = {}
    for f in findings:
        by_impact[f["impact"]] = by_impact.get(f["impact"], 0) + 1

    state.log(
        "AccessibilityAgent",
        "Accessibility audit complete",
        "success",
        f"{len(findings)} violations found ({by_impact})",
    )
    return state
