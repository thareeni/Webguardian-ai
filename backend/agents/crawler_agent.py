"""
Crawler Agent
=============
Uses Playwright to autonomously discover and inspect pages on a website.

For every page visited it collects:
  - page metadata (title, status code, load time)
  - a full-page screenshot (saved to disk, path stored in state)
  - console errors
  - failed network requests
  - a lightweight DOM inventory (forms, buttons, links, images) that the
    Functional Test Agent uses to *generate* tests dynamically - nothing
    here is hardcoded per-site.

This agent makes its own decisions: it decides which links are worth
following (same-origin, not mailto/tel/js-void, not already visited),
when to stop (max_pages / max_depth), and how to recover if a single
page fails to load (skip it, log it, keep going).
"""
from __future__ import annotations
import asyncio
import os
import time
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from .state import ScanState

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "storage", "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

DEVICE_VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}

DISALLOWED_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


def _same_origin(base: str, candidate: str) -> bool:
    b, c = urlparse(base), urlparse(candidate)
    return b.netloc == c.netloc


def _normalize(base: str, href: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(DISALLOWED_SCHEMES):
        return None
    absolute = urljoin(base, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    # strip fragments so #section links don't count as new pages
    return parsed._replace(fragment="").geturl()


async def _inspect_dom(page: Page) -> dict:
    """Extract a structured inventory of interactive elements for test generation."""
    return await page.evaluate(
        """
        () => {
            const forms = Array.from(document.querySelectorAll('form')).map((f, i) => ({
                index: i,
                action: f.action || null,
                method: (f.method || 'get').toUpperCase(),
                inputs: Array.from(f.querySelectorAll('input, textarea, select')).map(inp => ({
                    name: inp.name || null,
                    type: inp.type || inp.tagName.toLowerCase(),
                    required: inp.required || false,
                    id: inp.id || null,
                })),
            }));
            const buttons = Array.from(document.querySelectorAll('button, input[type=submit], [role=button]'))
                .slice(0, 40)
                .map(b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim())
                .filter(Boolean);
            const links = Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(Boolean);
            const images = Array.from(document.querySelectorAll('img')).map(img => ({
                src: img.src,
                alt: img.alt,
            }));
            return { forms, buttons, links, images, title: document.title };
        }
        """
    )


async def crawl_website(state: ScanState) -> ScanState:
    """BFS crawl of the target website, bounded by max_pages / max_depth."""
    state.log("CrawlerAgent", "Launching Playwright browser", "running")

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(state.website_url, 0)]
    viewport = DEVICE_VIEWPORTS.get(state.device, DEVICE_VIEWPORTS["desktop"])

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as e:
            # Self-healing: one retry on browser launch failure (spec section 21)
            state.log("CrawlerAgent", "Browser launch failed, retrying", "warning", str(e))
            await asyncio.sleep(1)
            browser = await pw.chromium.launch(headless=True)

        context = await browser.new_context(
            viewport=viewport,
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(15000)

        while queue and len(visited) < state.max_pages:
            url, depth = queue.pop(0)
            if url in visited or depth > state.max_depth:
                continue
            visited.add(url)

            page = await context.new_page()
            page_console_errors: list[dict] = []
            page_network_errors: list[dict] = []

            page.on(
                "console",
                lambda msg: page_console_errors.append({"type": msg.type, "text": msg.text})
                if msg.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda req: page_network_errors.append(
                    {
                        "url": req.url,
                        "failure": (
                            req.failure.get("errorText")
                            if isinstance(req.failure, dict)
                            else str(req.failure)
                        )
                        if req.failure
                        else "unknown",
                    }
                ),
            )

            start = time.monotonic()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except PWTimeout:
                # Self-healing: retry once with load event
                try:
                    response = await page.goto(url, wait_until="load", timeout=15000)
                except Exception as e:
                    state.log("CrawlerAgent", f"Skipping unreachable page: {url}", "warning", str(e))
                    await page.close()
                    continue
            except Exception as e:
                state.log("CrawlerAgent", f"Skipping unreachable page: {url}", "warning", str(e))
                await page.close()
                continue

            # Bounded extra wait for JS-heavy SPAs (e.g. React/Vue/Next.js) to render navigation links
            try:
                await page.wait_for_selector("a[href]", timeout=2500)
            except Exception:
                pass
            await asyncio.sleep(0.5)

            load_time_ms = round((time.monotonic() - start) * 1000, 1)
            status_code = response.status if response else None

            dom_inventory = await _inspect_dom(page)

            screenshot_name = f"{state.scan_id}_{len(visited)}.png"
            screenshot_path = os.path.join(SCREENSHOT_DIR, screenshot_name)
            try:
                await page.screenshot(path=screenshot_path, full_page=True, timeout=8000)
                state.screenshots.append({"url": url, "path": screenshot_path, "device": state.device})
            except Exception as e:
                state.log("CrawlerAgent", f"Screenshot failed for {url}", "warning", str(e))

            page_record = {
                "url": url,
                "depth": depth,
                "title": dom_inventory.get("title"),
                "status_code": status_code,
                "load_time_ms": load_time_ms,
                "forms": dom_inventory.get("forms", []),
                "buttons": dom_inventory.get("buttons", []),
                "links": dom_inventory.get("links", []),
                "images": dom_inventory.get("images", []),
            }
            state.pages.append(page_record)

            for e in page_console_errors:
                state.console_errors.append({"url": url, **e})
            for e in page_network_errors:
                state.network_errors.append({"url": url, **e})

            state.log(
                "CrawlerAgent",
                f"Inspected page {url}",
                "success",
                f"status={status_code}, forms={len(page_record['forms'])}, "
                f"links={len(page_record['links'])}, load_time={load_time_ms}ms",
            )

            if depth < state.max_depth:
                for href in dom_inventory.get("links", []):
                    normalized = _normalize(url, href)
                    if normalized and _same_origin(state.website_url, normalized) and normalized not in visited:
                        queue.append((normalized, depth + 1))

            await page.close()

        await browser.close()

    state.log(
        "CrawlerAgent",
        "Crawl complete",
        "success",
        f"{len(state.pages)} pages discovered (max_pages={state.max_pages}, max_depth={state.max_depth})",
    )
    return state
