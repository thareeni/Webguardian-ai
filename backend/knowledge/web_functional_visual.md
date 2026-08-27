# Web Functional, Visual Layout & Performance Guidelines

## 1. Broken Links & Unreachable Navigation (HTTP 404 / 500)
- **Violation**: Hyperlinks (`<a>` tags) leading to missing pages (HTTP 404 Not Found) or internal server failures (HTTP 500).
- **Root Cause**: Typos in `href` attributes, deleted or moved pages without 301 redirects, or unhandled server exceptions.
- **Fix**: Update or remove dead links. Implement 301 permanent redirects for moved URLs, and add automated automated link verification in CI/CD.

## 2. Unhandled JavaScript Console & Network Exceptions
- **Violation**: Unhandled runtime exceptions (`TypeError: Cannot read property of undefined`, `ReferenceError`) logged in browser console.
- **Root Cause**: Missing null/undefined checks before property access, unhandled API fetch rejections, or dynamic bundle loading errors.
- **Fix**: Implement optional chaining (`object?.property`), fallback values, and wrap async fetch calls in `try / catch` blocks.

## 3. Visual Layout Overlap & Component Collision
- **Violation**: Interactive elements (buttons, inputs, links) obscured or overlapped by floating headers, modals, or fixed position elements.
- **Root Cause**: Hardcoded `z-index` layering issues, improper `position: fixed` offset calculation, or grid/flexbox container overflow.
- **Fix**: Adjust `z-index` scale, add proper `margin` or `padding` offsets to scroll containers, and use CSS `pointer-events: none` on overlay backgrounds.

## 4. Horizontal Viewport Overflow
- **Violation**: Content width exceeds screen width (`scrollWidth > clientWidth`), introducing unwanted horizontal scrollbars.
- **Root Cause**: Fixed width elements (`width: 1200px`), unformatted pre tags, or large images exceeding container bounds.
- **Fix**: Replace fixed pixel widths with responsive percentages or max-width utilities (`max-width: 100%; box-sizing: border-box; overflow-x: hidden;`).

## 5. Slow Time To First Byte (TTFB) & Resource Load Bottlenecks
- **Violation**: TTFB exceeding 800ms or DOMContentLoaded duration exceeding 3.0 seconds.
- **Root Cause**: Uncached backend database queries, large uncompressed image payloads, or blocking third-party synchronous JavaScript.
- **Fix**: Enable server-side caching (Redis/CDN), compress assets (WebP images, gzip/brotli text), and load scripts asynchronously (`<script async src="...">`).
