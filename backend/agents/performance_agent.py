"""
Performance Agent
=================
Captures Navigation Timing and Resource Timing metrics using Playwright &
browser Performance APIs:
  - TTFB (Time to First Byte)
  - DOMContentLoaded time
  - Load Event time
  - DNS lookup time
  - Total resource count & total transfer size
  - Slow / bloated resource detection
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


async def audit_page_performance(page, url: str) -> dict:
    metrics = await page.evaluate("""
    () => {
        let ttfb = 0;
        let domContent = 0;
        let loadEvent = 0;
        let dns = 0;

        const navEntries = performance.getEntriesByType('navigation');
        if (navEntries && navEntries.length > 0) {
            const nav = navEntries[0];
            ttfb = Math.max(0, Math.round(nav.responseStart - nav.requestStart));
            domContent = Math.max(0, Math.round(nav.domContentLoadedEventEnd - nav.startTime));
            loadEvent = Math.max(0, Math.round(nav.loadEventEnd - nav.startTime));
            dns = Math.max(0, Math.round(nav.domainLookupEnd - nav.domainLookupStart));
        } else if (performance.timing) {
            const t = performance.timing;
            ttfb = Math.max(0, Math.round(t.responseStart - t.requestStart));
            domContent = Math.max(0, Math.round(t.domContentLoadedEventEnd - t.navigationStart));
            loadEvent = Math.max(0, Math.round(t.loadEventEnd - t.navigationStart));
            dns = Math.max(0, Math.round(t.domainLookupEnd - t.domainLookupStart));
        }

        const resources = performance.getEntriesByType('resource');
        let totalBytes = 0;
        const slowResources = [];

        for (const res of resources) {
            const size = res.transferSize || res.encodedBodySize || 0;
            totalBytes += size;
            if (res.duration > 500 || size > 500000) {
                slowResources.push({
                    name: res.name,
                    duration_ms: Math.round(res.duration),
                    size_bytes: size,
                    initiatorType: res.initiatorType,
                });
            }
        }

        return {
            ttfb_ms: ttfb,
            dom_content_loaded_ms: domContent,
            load_event_ms: loadEvent,
            dns_lookup_ms: dns,
            total_requests: resources.length + 1,
            total_bytes: totalBytes,
            slow_resources: slowResources.slice(0, 10),
        };
    }
    """)
    metrics["url"] = url
    return metrics


async def run_performance_audit(state: ScanState) -> ScanState:
    state.log("PerformanceAgent", "Measuring page navigation & resource timing", "running")

    metrics_list: list[dict] = []
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
                await page.goto(url, timeout=15000, wait_until="load")
                m = await asyncio.wait_for(audit_page_performance(page, url), timeout=10)
                metrics_list.append(m)
            except Exception as e:
                state.log("PerformanceAgent", f"Performance audit skipped for {url}", "warning", str(e))
            finally:
                await page.close()

        await browser.close()

    state.performance_metrics = metrics_list
    avg_ttfb = round(sum(m["ttfb_ms"] for m in metrics_list) / len(metrics_list)) if metrics_list else 0
    state.log(
        "PerformanceAgent",
        "Performance audit complete",
        "success",
        f"{len(metrics_list)} pages analyzed (avg TTFB={avg_ttfb}ms)",
    )
    return state
