"""
Root Cause Agent (RAG-Grounded AI Analysis with Claude API)
===========================================================
Enriches scan state bugs with RAG-retrieved knowledge and Claude AI root cause analysis.
Capped at top 15-20 bugs by severity (CRITICAL/HIGH first, then MEDIUM).
Resilient fallback to rule-based rationale if ANTHROPIC_API_KEY is missing or API call fails.
"""
from __future__ import annotations
import os
import json
import asyncio
from typing import List, Dict, Any

from .state import ScanState
from .rag_agent import retrieve_rag_context

SEVERITY_WEIGHTS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
TOP_AI_BUG_LIMIT = 15
CLAUDE_TIMEOUT_SECONDS = 10.0


def _rule_based_fallback(bug: Dict[str, Any], rag_context: str) -> tuple[str, str]:
    cat = bug.get("category", "general").capitalize()
    desc = bug.get("description", "")
    sev = bug.get("severity", "MEDIUM")
    page = bug.get("page_url", "")
    
    first_line = rag_context.split("\n")[0].strip("# ") if rag_context else "Standard web QA guideline"
    root_cause = f"[{sev} Severity - {cat}] Structural issue detected on page '{page}': {desc}. Knowledge reference: {first_line}."
    
    # Extract actionable fix lines from RAG context snippet
    fix_lines = [line.strip("- *") for line in rag_context.split("\n") if "Fix" in line or "Solution" in line or line.startswith("- ")]
    if fix_lines:
        suggested_fix = f"Actionable Remediations:\n" + "\n".join(f"• {fl}" for fl in fix_lines[:3])
    else:
        suggested_fix = f"Review WCAG/OWASP QA guidelines for {cat.lower()} compliance and update component markup or server configuration on '{page}'."
        
    return root_cause, suggested_fix


async def _analyze_bugs_with_claude(api_key: str, prioritized_bugs: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """
    Call Claude API to generate AI root cause & suggested fix for a batch of bugs.
    Returns dict: bug_id -> {"root_cause": ..., "suggested_fix": ...}
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)

    prompt_bugs = []
    for b in prioritized_bugs:
        prompt_bugs.append({
            "bug_id": b.get("id", ""),
            "category": b.get("category", ""),
            "severity": b.get("severity", ""),
            "page_url": b.get("page_url", ""),
            "description": b.get("description", ""),
            "evidence": b.get("evidence", {}),
            "rag_context": b.get("rag_context", "")[:400],
        })

    system_prompt = (
        "You are an expert QA and Web Security AI Analyst. "
        "Analyze the provided list of web QA bugs along with their RAG-retrieved context snippets. "
        "For each bug, produce a concise, professional root cause explanation (1-2 sentences) "
        "and a specific actionable suggested fix (1-2 sentences). "
        "Return ONLY a valid JSON object mapping bug_id to an object with keys 'root_cause' and 'suggested_fix'."
        "\nExample format:\n"
        '{\n  "BUG-001": {\n    "root_cause": "...",\n    "suggested_fix": "..."\n  }\n}'
    )

    user_prompt = f"Analyze these {len(prompt_bugs)} web bugs:\n" + json.dumps(prompt_bugs, indent=2)

    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content_text = response.content[0].text.strip()
    if content_text.startswith("```json"):
        content_text = content_text.split("```json")[1].split("```")[0].strip()
    elif content_text.startswith("```"):
        content_text = content_text.split("```")[1].split("```")[0].strip()

    return json.loads(content_text)


async def run_root_cause_agent(state: ScanState) -> ScanState:
    if state.scan_status == "failed" or not state.bugs:
        return state

    state.log("RootCauseAgent", f"Analyzing {len(state.bugs)} bugs with RAG knowledge retrieval", "running")

    # Step 1: Retrieve RAG context and populate rule-based defaults for all bugs
    for bug in state.bugs:
        desc = bug.get("description", "")
        cat = bug.get("category", "")
        ctx = retrieve_rag_context(desc, category=cat, top_k=2)
        bug["rag_context"] = ctx
        bug["rag_grounded"] = True

        # Default rule-based fallback values
        rc, sf = _rule_based_fallback(bug, ctx)
        bug["root_cause"] = rc
        bug["suggested_fix"] = sf
        bug["ai_generated"] = False

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        state.log("RootCauseAgent", "ANTHROPIC_API_KEY not set - using RAG-grounded rule-based rationale", "success")
        return state

    # Step 2: Prioritize top 15 bugs by severity
    sorted_bugs = sorted(
        state.bugs,
        key=lambda x: SEVERITY_WEIGHTS.get(x.get("severity", "LOW"), 1),
        reverse=True
    )
    prioritized_bugs = sorted_bugs[:TOP_AI_BUG_LIMIT]

    state.log("RootCauseAgent", f"Invoking Claude API for top {len(prioritized_bugs)} bugs by severity", "running")

    try:
        results = await asyncio.wait_for(
            _analyze_bugs_with_claude(api_key, prioritized_bugs),
            timeout=CLAUDE_TIMEOUT_SECONDS
        )

        success_count = 0
        bug_map = {b.get("id"): b for b in state.bugs}
        for bug_id, ai_res in results.items():
            if bug_id in bug_map and isinstance(ai_res, dict):
                target = bug_map[bug_id]
                if "root_cause" in ai_res:
                    target["root_cause"] = ai_res["root_cause"]
                if "suggested_fix" in ai_res:
                    target["suggested_fix"] = ai_res["suggested_fix"]
                target["ai_generated"] = True
                success_count += 1

        state.log("RootCauseAgent", f"Claude AI root cause analysis complete for {success_count} top bugs", "success")
    except Exception as e:
        state.log("RootCauseAgent", f"Claude API call failed/timed out - fell back to RAG rule-based rationale: {e}", "warning")

    return state
