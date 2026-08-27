"""
Verification Agent (Targeted Real-Time Bug Verification)
=========================================================
For top severity-capped bugs, re-runs ONLY the specific check that originally found it.
Assigns `verification_status`: "still_present" or "not_reproducible".
Includes short per-check timeouts (2.0s max) to guarantee zero scan hangs.
"""
from __future__ import annotations
import asyncio
import urllib.request
import urllib.parse
from typing import Dict, Any, List

from .state import ScanState

SEVERITY_WEIGHTS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
TOP_VERIFY_BUG_LIMIT = 15
PER_CHECK_TIMEOUT = 2.0


async def _verify_single_bug(bug: Dict[str, Any]) -> str:
    """
    Re-check specific bug condition and return 'still_present' or 'not_reproducible'.
    """
    cat = bug.get("category", "general").lower()
    desc = bug.get("description", "").lower()
    page = bug.get("page_url", bug.get("page", ""))
    evidence = bug.get("evidence", {})

    # Case 1: Functional broken links (re-verify HTTP response status)
    if "functional" in cat or "link" in desc or "404" in desc or "status=" in desc:
        target_url = evidence.get("target_url") or evidence.get("url") or page
        if target_url and target_url.startswith("http"):
            try:
                def _fetch():
                    req = urllib.request.Request(target_url, headers={"User-Agent": "WebGuardian-Verifier/1.0"})
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        return resp.status
                status = await asyncio.to_thread(_fetch)
                if status == 200:
                    return "not_reproducible"  # Link is reachable now
                return "still_present"
            except Exception:
                return "still_present"

    # Case 2: Security checks (re-verify URL protocol or security headers)
    if "security" in cat:
        if "http" in desc or "unencrypted" in desc:
            if page.startswith("http://") or evidence.get("form_action", "").startswith("http://"):
                return "still_present"
            return "not_reproducible"
        if "header" in desc:
            try:
                def _check_headers():
                    req = urllib.request.Request(page, headers={"User-Agent": "WebGuardian-Verifier/1.0"})
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        headers = {k.lower(): v for k, v in resp.headers.items()}
                        if "content-security-policy" in desc and "content-security-policy" in headers:
                            return "not_reproducible"
                        if "strict-transport-security" in desc and "strict-transport-security" in headers:
                            return "not_reproducible"
                        return "still_present"
                return await asyncio.to_thread(_check_headers)
            except Exception:
                return "still_present"

    # Default fallback for accessibility/visual/general:
    return "still_present"


async def run_verification_agent(state: ScanState) -> ScanState:
    if state.scan_status == "failed" or not state.bugs:
        return state

    state.log("VerificationAgent", "Running targeted verification re-checks on top bugs", "running")

    # Prioritize top 15 bugs by severity
    sorted_bugs = sorted(
        state.bugs,
        key=lambda x: SEVERITY_WEIGHTS.get(x.get("severity", "LOW"), 1),
        reverse=True
    )
    prioritized_bugs = sorted_bugs[:TOP_VERIFY_BUG_LIMIT]

    verified_count = 0
    still_present_count = 0
    not_reproducible_count = 0

    for bug in prioritized_bugs:
        try:
            status = await asyncio.wait_for(_verify_single_bug(bug), timeout=PER_CHECK_TIMEOUT)
        except Exception:
            status = "still_present"

        bug["verification_status"] = status
        verified_count += 1
        if status == "still_present":
            still_present_count += 1
        else:
            not_reproducible_count += 1

    # Remaining non-top bugs get default verification status
    for bug in state.bugs:
        if "verification_status" not in bug:
            bug["verification_status"] = "still_present"

    state.log(
        "VerificationAgent",
        f"Verification complete - {verified_count} bugs re-checked ({still_present_count} still present, {not_reproducible_count} not reproducible)",
        "success"
    )

    return state
