# OWASP Web Security Posture & Hardening Guidelines

## 1. Missing HTTP Security Headers
- **Violation**: Web server responses lack critical HTTP security headers: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.
- **Root Cause**: Default web server configurations (Nginx, Apache, FastAPI, Cloudflare) do not include security headers automatically.
- **Fix**: Configure application middleware or web server headers:
  - `Content-Security-Policy`: Define trusted sources for scripts, styles, and frames (e.g., `default-src 'self'`).
  - `Strict-Transport-Security` (HSTS): Enforce HTTPS connections (e.g., `max-age=31536000; includeSubDomains`).
  - `X-Content-Type-Options`: Prevent MIME-type sniffing (`nosniff`).
  - `X-Frame-Options`: Prevent Clickjacking attacks (`DENY` or `SAMEORIGIN`).
  - `Referrer-Policy`: Protect sensitive URL query parameters (`strict-origin-when-cross-origin`).

## 2. Insecure Form Submissions over HTTP
- **Violation**: HTML forms defined on HTTPS pages with an `action` attribute submitting over unencrypted `http://` protocols or missing HTTPS.
- **Root Cause**: Hardcoded legacy HTTP endpoints in form action attributes or relative protocol mismatches.
- **Fix**: Ensure all form actions point to secure HTTPS URLs (`action="https://example.com/api/submit"` or relative path `/api/submit`) and redirect all HTTP traffic to HTTPS at the web server level.

## 3. Mixed Content Security Vulnerability
- **Violation**: A secure page (`https://`) loads external assets (images, scripts, stylesheets, audio, video) over insecure HTTP (`http://`).
- **Root Cause**: Absolute legacy HTTP asset URLs hardcoded in HTML markup or script bundles.
- **Fix**: Change asset URLs from `http://` to relative paths or secure `https://` schemes. Enable `upgrade-insecure-requests` directive in CSP.

## 4. Exposed Sensitive Endpoints & Information Leakage
- **Violation**: Public availability of sensitive endpoints such as `/admin`, `/.git`, `/backup.sql`, `/config.json`, or `/api/v1/debug`.
- **Root Cause**: Missing access control restrictions, deployment artifacts left in document root, or debug mode enabled in production.
- **Fix**: Restrict administrative endpoints behind authentication & IP whitelisting. Ensure `.git`, `.env`, and backup files are excluded from web root deployment.
