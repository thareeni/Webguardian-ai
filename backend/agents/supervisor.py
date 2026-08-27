"""
Supervisor Agent (LangGraph StateGraph Orchestration)
======================================================
Central orchestrator refactored into a formal LangGraph StateGraph.
Explicit workflow nodes:
  validate_url -> crawler -> functional -> accessibility -> specialized_analysis (Visual, Perf, Sec in parallel) -> bug_aggregator -> quality_score -> END

Conditional edge after crawler node enforces PLAN -> ACT -> OBSERVE -> ANALYZE -> DECIDE pipeline decisions.
"""
from __future__ import annotations
import asyncio
from urllib.parse import urlparse
from langgraph.graph import StateGraph, END

from .state import ScanState
from .crawler_agent import crawl_website
from .functional_agent import run_functional_tests
from .accessibility_agent import run_accessibility_audit
from .visual_agent import run_visual_audit
from .performance_agent import run_performance_audit
from .security_agent import run_security_audit
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


async def node_validate(state: ScanState) -> ScanState:
    state.scan_status = "running"
    state.log("Supervisor", "Received scan request", "running", state.website_url)
    err = validate_url(state.website_url)
    if err:
        state.scan_status = "failed"
        state.error = err
        state.log("Supervisor", "URL validation failed", "failed", err)
    else:
        state.log(
            "Supervisor",
            "LangGraph plan: Crawl -> Functional -> Accessibility -> Concurrent Specialized Analysis (Visual/Perf/Sec) -> Bug Intelligence -> Score",
            "success",
        )
    return state


async def node_crawl(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
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


async def node_functional(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = await run_functional_tests(state)
    except Exception as e:
        state.log("Supervisor", "Functional Agent failed - continuing without functional results", "warning", str(e))
    return state


async def node_accessibility(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = await run_accessibility_audit(state)
    except Exception as e:
        state.log("Supervisor", "Accessibility Agent failed - continuing without a11y results", "warning", str(e))
    return state


async def node_specialized_analysis(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    state.log(
        "Supervisor",
        "Executing specialized analysis agents concurrently (Visual, Performance, Security)",
        "running",
    )
    results = await asyncio.gather(
        run_visual_audit(state),
        run_performance_audit(state),
        run_security_audit(state),
        return_exceptions=True,
    )
    for res in results:
        if isinstance(res, Exception):
            state.log("Supervisor", "Specialized analysis agent encountered an issue", "warning", str(res))
    return state


from .root_cause_agent import run_root_cause_agent
from .fix_agent import run_fix_agent
from .verification_agent import run_verification_agent


async def node_root_cause(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = await run_root_cause_agent(state)
    except Exception as e:
        state.log("Supervisor", "Root Cause Agent failed", "warning", str(e))
    return state


async def node_fix(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = await run_fix_agent(state)
    except Exception as e:
        state.log("Supervisor", "Fix Agent failed", "warning", str(e))
    return state


async def node_verification(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = await run_verification_agent(state)
    except Exception as e:
        state.log("Supervisor", "Verification Agent failed", "warning", str(e))
    return state


async def node_bug_aggregator(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
    try:
        state = aggregate_bugs(state)
    except Exception as e:
        state.log("Supervisor", "Bug aggregation failed", "warning", str(e))
    return state


async def node_quality_score(state: ScanState) -> ScanState:
    if state.scan_status == "failed":
        return state
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
        f"{len(state.pages)} pages, {len(state.bugs)} bugs, score={state.quality_score['overall'] if state.quality_score else 'n/a'}",
    )
    return state


def check_crawl_success(state: ScanState) -> str:
    if state.scan_status == "failed" or not state.pages:
        return "abort"
    return "continue"


# Build explicit LangGraph StateGraph
workflow = StateGraph(ScanState)

workflow.add_node("validate_url", node_validate)
workflow.add_node("crawler", node_crawl)
workflow.add_node("functional", node_functional)
workflow.add_node("accessibility", node_accessibility)
workflow.add_node("specialized_analysis", node_specialized_analysis)
workflow.add_node("bug_aggregator", node_bug_aggregator)
workflow.add_node("root_cause", node_root_cause)
workflow.add_node("fix", node_fix)
workflow.add_node("verification", node_verification)
workflow.add_node("quality_score", node_quality_score)

workflow.set_entry_point("validate_url")
workflow.add_edge("validate_url", "crawler")
workflow.add_conditional_edges(
    "crawler",
    check_crawl_success,
    {
        "abort": END,
        "continue": "functional",
    },
)
workflow.add_edge("functional", "accessibility")
workflow.add_edge("accessibility", "specialized_analysis")
workflow.add_edge("specialized_analysis", "bug_aggregator")
workflow.add_edge("bug_aggregator", "root_cause")
workflow.add_edge("root_cause", "fix")
workflow.add_edge("fix", "verification")
workflow.add_edge("verification", "quality_score")
workflow.add_edge("quality_score", END)

app_graph = workflow.compile()


async def run_scan(state: ScanState) -> ScanState:
    res = await app_graph.ainvoke(state)
    if isinstance(res, dict):
        for key, val in res.items():
            if hasattr(state, key):
                setattr(state, key, val)
        return state
    return res
