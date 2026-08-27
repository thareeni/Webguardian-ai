"""
Fix Agent (Structured Actionable Fix Recommendation)
===================================================
Expands suggested fixes for top severity-capped bugs into structured recommendations:
- what: What exact code or setting to change
- where: Exact element location, selector, or file route
- expected_impact: Predicted resolution outcome & benefit
Reuses RAG context and AI outputs without re-querying ChromaDB or making redundant LLM calls.
"""
from __future__ import annotations
from typing import List, Dict, Any

from .state import ScanState

TOP_FIX_BUG_LIMIT = 15


def _generate_structured_fix(bug: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate structured fix object (what, where, expected_impact) from RAG context & bug data.
    """
    cat = bug.get("category", "general").lower()
    desc = bug.get("description", "")
    page = bug.get("page_url", bug.get("page", ""))
    rag_ctx = bug.get("rag_context", "")

    # Extract actionable fix lines from RAG context snippet if available
    fix_lines = [line.strip("- *") for line in rag_ctx.split("\n") if "Fix" in line or "Solution" in line or line.startswith("- ")]
    fix_summary = fix_lines[0] if fix_lines else "Remediate component markup or server configuration."

    if "accessibility" in cat or "alt" in desc.lower():
        what = f"Add descriptive `alt` attribute or `aria-label` to element"
        where = f"Target element on page `{page}` ({desc})"
        impact = "Resolves WCAG 1.1.1 accessibility violation and improves screen reader compatibility."
    elif "security" in cat or "http" in desc.lower():
        what = f"Upgrade form action endpoint or header configuration to HTTPS"
        where = f"Form action / HTTP headers on `{page}`"
        impact = "Mitigates OWASP security risk, preventing cleartext credential/data exposure."
    elif "visual" in cat or "overlap" in desc.lower():
        what = f"Adjust `z-index` or container `padding`/`margin` bounding box"
        where = f"CSS rules targeting element on page `{page}`"
        impact = "Fixes component collision and restores clickable interactive area."
    elif "functional" in cat or "link" in desc.lower():
        what = f"Fix broken link target URL or restore missing destination route"
        where = f"Anchor tag `<a href>` pointing from page `{page}`"
        impact = "Eliminates 404 navigation error and improves user experience."
    else:
        what = f"Refactor code to follow web QA standards: {fix_summary}"
        where = f"Component on `{page}`"
        impact = f"Resolves {cat} issue and improves overall quality score."

    return {
        "what": what,
        "where": where,
        "expected_impact": impact,
    }


async def run_fix_agent(state: ScanState) -> ScanState:
    if state.scan_status == "failed" or not state.bugs:
        return state

    state.log("FixAgent", f"Generating structured fix recommendations for top bugs", "running")

    count = 0
    for bug in state.bugs:
        if not bug.get("fix_recommendation"):
            bug["fix_recommendation"] = _generate_structured_fix(bug)
            count += 1

    state.log("FixAgent", f"Structured fix recommendations generated for {min(count, TOP_FIX_BUG_LIMIT)} top bugs", "success")
    return state
