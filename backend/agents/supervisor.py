"""
Supervisor Agent
=================
Central orchestrator. Owns the shared ScanState, decides which agents to
run, in what order, and how to react when an agent fails - this is the
piece that makes the system "agentic" rather than a fixed script:

  - It inspects results after each stage and DECIDES the next step
    (e.g. skip the Accessibility Agent entirely if the crawl found 0 pages,
    rather than blindly running every agent regardless of state).
  - If an agent throws, it's caught, logged as FAILED, and the pipeline
    continues with whatever agents can still produce value (self-healing /
    graceful degradation, spec section 21) instead of the whole scan dying.

Phase 1 pipeline:
    Crawler -> Functional -> Accessibility -> Bug Intelligence -> Score

Phase 2/3 will insert Visual / Performance / Security / Root Cause / RAG /
Fix / Verification agents into this same run_scan() function, each guarded
by the same try/except + conditional-skip pattern established here.
"""
from __future__ import annotations
from urllib.parse import urlparse

from .state import ScanState
from .crawler_agent import crawl_website
from .functional_agent import run_functional_tests
from .accessibility_agent import run_accessibility_audit
from .bug_aggregator import aggregate_bugs, compute_quality_score


def validate_url(url: str) -> str | None:
    """Basic SSRF / sanity guardrails (spec section 34). Returns an error message or None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "URL must start with http:// or https://"
    host = parsed.hostname or ""
    if host.startswith("192.168.") or host.startswith("10."):
        return "Scanning local/private network addresses is not permitted."
    return None


async def run_scan(state: ScanState) -> ScanState:
    state.scan_status = "running"
    state.log("Supervisor", "Received scan request", "running", state.website_url)

    error = validate_url(state.website_url)
    if error:
        state.scan_status = "failed"
        state.error = error
        state.log("Supervisor", "URL validation failed", "failed", error)
        return state

    state.log(
        "Supervisor",
        "Created scan plan: Crawl -> Functional Tests -> Accessibility Audit -> Bug Aggregation -> Score",
        "success",
    )

    # --- Stage 1: Crawl ---
    try:
        state = await crawl_website(state)
    except Exception as e:
        state.log("Supervisor", "Crawler Agent failed entirely", "failed", str(e))
        state.scan_status = "failed"
        state.error = f"Crawl failed: {e}"
        return state

    if not state.pages:
        state.log(
            "Supervisor",
            "No pages were successfully crawled - aborting downstream agents",
            "failed",
        )
        state.scan_status = "failed"
        state.error = "No reachable pages found at the target URL."
        return state

    # --- Stage 2: Functional testing (conditional: only if pages have testable elements) ---
    try:
        state = await run_functional_tests(state)
    except Exception as e:
        state.log("Supervisor", "Functional Agent failed - continuing without functional results", "warning", str(e))

    # --- Stage 3: Accessibility audit ---
    try:
        state = await run_accessibility_audit(state)
    except Exception as e:
        state.log(
            "Supervisor", "Accessibility Agent failed - continuing without a11y results", "warning", str(e)
        )

    # --- Stage 4: Bug Intelligence (merge + dedupe + severity) ---
    try:
        state = aggregate_bugs(state)
    except Exception as e:
        state.log("Supervisor", "Bug aggregation failed", "warning", str(e))

    # --- Stage 5: Quality score ---
    try:
        state = compute_quality_score(state)
    except Exception as e:
        state.log("Supervisor", "Quality score computation failed", "warning", str(e))

    state.scan_status = "completed"
    from .state import now_iso

    state.finished_at = now_iso()
    state.log(
        "Supervisor",
        "Scan complete",
        "success",
        f"{len(state.pages)} pages, {len(state.bugs)} bugs, "
        f"score={state.quality_score['overall'] if state.quality_score else 'n/a'}",
    )
    return state
