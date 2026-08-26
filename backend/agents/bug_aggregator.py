"""
Bug Intelligence Agent (Phase 1 slice)
=======================================
Merges findings from the Functional Agent, Accessibility Agent, and raw
console/network errors into a single deduplicated bug list, each with an
assigned severity and a one-line rationale for that severity.

Phase 2/3 will extend this with the Root Cause Agent + RAG Agent; Phase 1
already produces a real, non-hardcoded bug list from whatever the crawl
actually found.
"""
from __future__ import annotations
import uuid

from .state import ScanState

AXE_IMPACT_TO_SEVERITY = {
    "critical": "CRITICAL",
    "serious": "HIGH",
    "moderate": "MEDIUM",
    "minor": "LOW",
}


def _bug_id() -> str:
    return f"BUG-{uuid.uuid4().hex[:6].upper()}"


def aggregate_bugs(state: ScanState) -> ScanState:
    state.log("BugIntelligenceAgent", "Merging findings from all agents", "running")

    bugs: list[dict] = []

    # --- from functional test failures ---
    for t in state.functional_tests:
        if t["status"] != "FAIL":
            continue
        if t["category"] == "navigation":
            severity = "HIGH"
            rationale = "Broken/unreachable link directly blocks user navigation."
        elif t["category"] == "form":
            severity = "CRITICAL"
            rationale = "Form accepts invalid/empty submission, risking bad data or broken flows."
        elif t["category"] == "media":
            severity = "LOW"
            rationale = "Broken image degrades visual quality but does not block functionality."
        else:
            severity = "MEDIUM"
            rationale = "Functional test failure detected."
        bugs.append(
            {
                "id": _bug_id(),
                "title": t["name"],
                "category": "functional",
                "page": t["page"],
                "severity": severity,
                "severity_rationale": rationale,
                "evidence": [{"type": "functional_test", "detail": t.get("evidence", "")}],
                "source_agents": ["FunctionalAgent"],
            }
        )

    # --- from accessibility violations ---
    for f in state.accessibility_findings:
        severity = AXE_IMPACT_TO_SEVERITY.get(f["impact"], "MEDIUM")
        bugs.append(
            {
                "id": _bug_id(),
                "title": f"{f['help']} ({f['rule_id']})",
                "category": "accessibility",
                "page": f["page"],
                "severity": severity,
                "severity_rationale": f"axe-core reports '{f['impact']}' impact, "
                f"affecting {f['nodes_affected']} element(s); WCAG guidance: {f['help_url']}",
                "evidence": [{"type": "axe_violation", "detail": f.get("example_selector", "")}],
                "source_agents": ["AccessibilityAgent"],
            }
        )

    # --- from raw console errors (dedup by message text) ---
    seen_console = set()
    for c in state.console_errors:
        key = c["text"][:120]
        if key in seen_console:
            continue
        seen_console.add(key)
        bugs.append(
            {
                "id": _bug_id(),
                "title": f"JavaScript console error: {c['text'][:100]}",
                "category": "functional",
                "page": c["url"],
                "severity": "MEDIUM",
                "severity_rationale": "Uncaught JS error may break interactivity for some users.",
                "evidence": [{"type": "console_error", "detail": c["text"]}],
                "source_agents": ["CrawlerAgent"],
            }
        )

    # --- from raw network errors ---
    seen_net = set()
    for n in state.network_errors:
        key = (n["url"], n["failure"])
        if key in seen_net:
            continue
        seen_net.add(key)
        bugs.append(
            {
                "id": _bug_id(),
                "title": f"Failed network request: {n['url'][:80]}",
                "category": "functional",
                "page": n["url"],
                "severity": "HIGH",
                "severity_rationale": f"Request failed ({n['failure']}); may break page functionality.",
                "evidence": [{"type": "network_error", "detail": n["failure"]}],
                "source_agents": ["CrawlerAgent"],
            }
        )

    state.bugs = bugs
    counts = {}
    for b in bugs:
        counts[b["severity"]] = counts.get(b["severity"], 0) + 1

    state.log("BugIntelligenceAgent", "Bug aggregation complete", "success", f"{len(bugs)} bugs ({counts})")
    return state


def compute_quality_score(state: ScanState) -> ScanState:
    state.log("Supervisor", "Computing overall quality score", "running")

    total_tests = len(state.functional_tests)
    passed_tests = sum(1 for t in state.functional_tests if t["status"] == "PASS")
    functional_score = round((passed_tests / total_tests) * 100) if total_tests else 100

    a11y_penalty = sum(
        {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 4, "LOW": 1}.get(f_sev, 2)
        for f_sev in (AXE_IMPACT_TO_SEVERITY.get(f["impact"], "MEDIUM") for f in state.accessibility_findings)
    )
    accessibility_score = max(0, 100 - a11y_penalty)

    severity_weights = {"CRITICAL": 20, "HIGH": 10, "MEDIUM": 5, "LOW": 2, "INFO": 0}
    overall_penalty = sum(severity_weights.get(b["severity"], 3) for b in state.bugs)
    overall = max(0, round(100 - (overall_penalty * 0.6)))

    state.quality_score = {
        "overall": overall,
        "functional": functional_score,
        "accessibility": accessibility_score,
        "pages_scanned": len(state.pages),
        "tests_generated": total_tests,
        "tests_passed": passed_tests,
        "bugs_found": len(state.bugs),
    }
    state.log("Supervisor", "Quality score computed", "success", str(state.quality_score))
    return state
