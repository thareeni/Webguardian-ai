# WCAG 2.1 Accessibility Best Practices & Fixes

## 1. Image Text Alternatives (WCAG 1.1.1)
- **Violation**: `<img>` elements missing an `alt` attribute or possessing an empty `alt` tag on informative visual content.
- **Root Cause**: Developers often omit `alt` attributes when embedding images or rely on CSS background images for content.
- **Fix**: Add a descriptive `alt` attribute describing the content and function of the image (e.g., `alt="Company Logo"`). For purely decorative images, explicitly specify `alt=""` and `aria-hidden="true"`.

## 2. Accessible Form Controls (WCAG 1.3.1 / 4.1.2)
- **Violation**: Input controls (`<input>`, `<select>`, `<textarea>`) lacking an associated `<label>` or `aria-label`.
- **Root Cause**: Relying solely on `placeholder` text or visual text next to inputs without binding via `<label for="id">`.
- **Fix**: Wrap inputs in explicit `<label>` tags or use `<label for="element_id">Label Text</label>`. Alternatively, add an `aria-label="Search"` attribute directly to the control.

## 3. Unlabeled Interactive Buttons & Links (WCAG 4.1.2)
- **Violation**: `<button>` or `<a>` elements containing only icon graphics (SVG/i tags) without accessible inner text.
- **Root Cause**: Designing icon-only buttons (e.g., cart, menu, search) without hidden accessibility labels.
- **Fix**: Include visually hidden text (`<span class="sr-only">Close Menu</span>`) or attach an `aria-label` attribute (e.g., `aria-label="Open Shopping Cart"`).

## 4. Minimum Color Contrast (WCAG 1.4.3)
- **Violation**: Text color contrast against its background is lower than 4.5:1 for normal text or 3:1 for large text.
- **Root Cause**: Using faint gray text (#888888) on light gray or white backgrounds for aesthetic design choices.
- **Fix**: Darken text colors or lighten background colors to satisfy WCAG AA contrast standard (minimum 4.5:1 ratio).

## 5. Keyboard Focus Visibility (WCAG 2.4.7)
- **Violation**: Interactive elements missing a visible focus indicator when navigated via Keyboard Tab.
- **Root Cause**: Applying CSS styles like `outline: none` or `outline: 0` without providing a custom `:focus-visible` outline.
- **Fix**: Remove `outline: none` or provide custom `:focus-visible` styles with a high-contrast ring (e.g., `outline: 2px solid #2563eb; outline-offset: 2px;`).
