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

    # --- from visual findings ---
    for vf in state.visual_findings:
        severity = vf.get("severity", "MEDIUM")
        bugs.append(
            {
                "id": _bug_id(),
                "title": f"Visual layout defect ({vf['type']}): {vf['selector']}",
                "category": "visual",
                "page": vf["page"],
                "severity": severity,
                "severity_rationale": vf["description"],
                "evidence": [{"type": "visual_layout", "detail": vf["description"]}],
                "source_agents": ["VisualAgent"],
            }
        )

    # --- from performance metrics ---
    for pm in state.performance_metrics:
        if pm.get("ttfb_ms", 0) > 1000:
            bugs.append(
                {
                    "id": _bug_id(),
                    "title": f"High Time To First Byte (TTFB): {pm['ttfb_ms']}ms",
                    "category": "performance",
                    "page": pm["url"],
                    "severity": "HIGH",
                    "severity_rationale": f"TTFB of {pm['ttfb_ms']}ms exceeds recommended 1000ms threshold.",
                    "evidence": [{"type": "performance_metric", "detail": f"TTFB={pm['ttfb_ms']}ms"}],
                    "source_agents": ["PerformanceAgent"],
                }
            )
        if pm.get("load_event_ms", 0) > 3000:
            bugs.append(
                {
                    "id": _bug_id(),
                    "title": f"Slow page load event: {pm['load_event_ms']}ms",
                    "category": "performance",
                    "page": pm["url"],
                    "severity": "MEDIUM",
                    "severity_rationale": f"Load event completed in {pm['load_event_ms']}ms (>3000ms threshold).",
                    "evidence": [{"type": "performance_metric", "detail": f"Load={pm['load_event_ms']}ms"}],
                    "source_agents": ["PerformanceAgent"],
                }
            )
        for sr in pm.get("slow_resources", [])[:3]:
            bugs.append(
                {
                    "id": _bug_id(),
                    "title": f"Slow resource load: {sr['name'][:60]} ({sr['duration_ms']}ms)",
                    "category": "performance",
                    "page": pm["url"],
                    "severity": "LOW",
                    "severity_rationale": f"Resource took {sr['duration_ms']}ms to load (size={sr['size_bytes']}B).",
                    "evidence": [{"type": "slow_resource", "detail": sr["name"]}],
                    "source_agents": ["PerformanceAgent"],
                }
            )

    # --- from security findings ---
    for sf in state.security_findings:
        severity = sf.get("severity", "MEDIUM")
        bugs.append(
            {
                "id": _bug_id(),
                "title": f"Security vulnerability ({sf['rule']}): {sf['description'][:100]}",
                "category": "security",
                "page": sf["page"],
                "severity": severity,
                "severity_rationale": sf["description"],
                "evidence": [{"type": "security_finding", "detail": sf.get("evidence", "")}],
                "source_agents": ["SecurityAgent"],
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

    visual_penalty = sum(
        {"CRITICAL": 15, "HIGH": 10, "MEDIUM": 5, "LOW": 2}.get(vf.get("severity"), 3)
        for vf in state.visual_findings
    )
    visual_score = max(0, 100 - visual_penalty)

    perf_bugs = [b for b in state.bugs if b.get("category") == "performance"]
    perf_penalty = sum(
        {"CRITICAL": 15, "HIGH": 10, "MEDIUM": 5, "LOW": 2}.get(b.get("severity"), 3)
        for b in perf_bugs
    )
    performance_score = max(0, 100 - perf_penalty)

    sec_penalty = sum(
        {"CRITICAL": 15, "HIGH": 10, "MEDIUM": 5, "LOW": 2}.get(sf.get("severity"), 3)
        for sf in state.security_findings
    )
    security_score = max(0, 100 - sec_penalty)

    # Average sub-scores so bug counts across multiple pages do not force overall score to 0
    scores = [functional_score, accessibility_score, visual_score, performance_score, security_score]
    overall = max(0, min(100, round(sum(scores) / len(scores))))

    state.quality_score = {
        "overall": overall,
        "functional": functional_score,
        "accessibility": accessibility_score,
        "visual": visual_score,
        "performance": performance_score,
        "security": security_score,
        "pages_scanned": len(state.pages),
        "tests_generated": total_tests,
        "tests_passed": passed_tests,
        "bugs_found": len(state.bugs),
    }
    state.log("Supervisor", "Quality score computed", "success", str(state.quality_score))
    return state
