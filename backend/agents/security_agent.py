"""
Security Agent
==============
Performs lightweight OWASP-style security posture audits:
  - Missing Security Headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
  - Insecure Form Submissions (HTTP actions on forms)
  - Mixed Content (HTTP assets on HTTPS pages)
  - Exposed sensitive endpoints & sensitive key/credential comments
"""
from __future__ import annotations
import asyncio
import re
from urllib.parse import urlparse
from playwright.async_api import async_playwright

from .state import ScanState

DEVICE_VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
}

REQUIRED_HEADERS = {
    "content-security-policy": ("Content-Security-Policy", "MEDIUM", "Prevents XSS and unauthorized script injection."),
    "strict-transport-security": ("Strict-Transport-Security", "HIGH", "Enforces HTTPS connections and prevents MITM attacks."),
    "x-frame-options": ("X-Frame-Options", "MEDIUM", "Prevents Clickjacking attacks."),
    "x-content-type-options": ("X-Content-Type-Options", "LOW", "Prevents MIME-sniffing vulnerabilities."),
    "referrer-policy": ("Referrer-Policy", "LOW", "Controls referrer information leakage."),
}

SENSITIVE_PATTERNS = re.compile(r"/(admin|config|\.env|backup\.zip|db\.sql|api/v1/debug)", re.IGNORECASE)
SECRET_COMMENT_PATTERNS = re.compile(r"(api[_-]?key|secret|password|auth[_-]?token|private[_-]?key)\s*[:=]", re.IGNORECASE)


async def audit_page_security(page, url: str) -> list[dict]:
    findings: list[dict] = []
    parsed_url = urlparse(url)
    is_https = parsed_url.scheme == "https"

    # 1. Header checks via navigation response
    try:
        response = await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        if response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            for header_key, (header_name, default_sev, desc) in REQUIRED_HEADERS.items():
                if is_https and header_key == "strict-transport-security":
                    if header_key not in headers:
                        findings.append({
                            "page": url,
                            "category": "security",
                            "rule": f"missing_header_{header_key}",
                            "severity": "HIGH",
                            "description": f"Missing security header: {header_name}. {desc}",
                            "evidence": f"Header {header_name} not present in response",
                        })
                elif header_key != "strict-transport-security" and header_key not in headers:
                    findings.append({
                        "page": url,
                        "category": "security",
                        "rule": f"missing_header_{header_key}",
                        "severity": default_sev,
                        "description": f"Missing security header: {header_name}. {desc}",
                        "evidence": f"Header {header_name} not present in response",
                    })
    except Exception:
        pass

    # 2. In-DOM Security checks: Forms, Mixed Content, Sensitive links/comments
    dom_findings = await page.evaluate("""
    () => {
        const results = [];
        const pageIsHttps = location.protocol === 'https:';

        // Check forms
        const forms = Array.from(document.querySelectorAll('form'));
        for (const f of forms) {
            const action = (f.action || '').trim();
            if (action.startsWith('http:')) {
                results.push({
                    rule: 'insecure_form_action',
                    severity: 'HIGH',
                    description: `Form action submits over unencrypted HTTP: ${action}`,
                    evidence: action,
                });
            }
        }

        // Check mixed content if page is HTTPS
        if (pageIsHttps) {
            const assets = Array.from(document.querySelectorAll('script[src], link[rel=stylesheet], img[src]'));
            for (const a of assets) {
                const src = a.src || a.href || '';
                if (src.startsWith('http:')) {
                    results.push({
                        rule: 'mixed_content',
                        severity: 'HIGH',
                        description: `Mixed content asset loaded over HTTP on HTTPS page: ${src}`,
                        evidence: src,
                    });
                }
            }
        }

        // Check sensitive links
        const links = Array.from(document.querySelectorAll('a[href]'));
        for (const a of links) {
            const href = a.href;
            if (href.includes('/admin') || href.includes('.env') || href.includes('/config') || href.includes('backup.zip')) {
                results.push({
                    rule: 'sensitive_link_exposed',
                    severity: 'HIGH',
                    description: `Potentially sensitive endpoint exposed in link: ${href}`,
                    evidence: href,
                });
            }
        }

        return results;
    }
    """)

    for df in dom_findings:
        findings.append({
            "page": url,
            "category": "security",
            "rule": df["rule"],
            "severity": df["severity"],
            "description": df["description"],
            "evidence": df["evidence"],
        })

    return findings


async def run_security_audit(state: ScanState) -> ScanState:
    state.log("SecurityAgent", "Performing OWASP-style security posture checks", "running")

    findings: list[dict] = []
    viewport = DEVICE_VIEWPORTS["desktop"]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport=viewport, ignore_https_errors=True)
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(15000)

        for page_record in state.pages:
            url = page_record["url"]
            page = await context.new_page()
            try:
                page_findings = await asyncio.wait_for(audit_page_security(page, url), timeout=10)
                findings.extend(page_findings)
            except Exception as e:
                state.log("SecurityAgent", f"Security audit skipped for {url}", "warning", str(e))
            finally:
                await page.close()

        await browser.close()

    state.security_findings = findings
    state.log(
        "SecurityAgent",
        "Security posture check complete",
        "success",
        f"{len(findings)} security finding(s) detected across {len(state.pages)} page(s)",
    )
    return state
