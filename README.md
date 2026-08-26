# WebGuardian AI — Phase 1

Autonomous Website QA agent. Give it a URL, it crawls the site with a real
browser, generates and runs tests based on what it actually finds on each
page (not a fixed checklist), audits accessibility with axe-core, and
produces a severity-ranked bug list and quality score — live, in a
dashboard, with no hardcoded per-site logic.

## What Phase 1 implements

```
URL → Supervisor → Crawler Agent (Playwright) → Functional Test Agent
    → Accessibility Agent (axe-core) → Bug Intelligence → Quality Score
    → Dashboard
```

- **Supervisor Agent** (`backend/agents/supervisor.py`) — validates the URL,
  builds the plan, runs each agent, and **decides what happens on failure**:
  if the crawl finds zero pages it aborts early instead of running dead
  agents; if the Functional or Accessibility agent throws, it logs a
  warning and keeps going with partial results instead of killing the scan.
  This conditional branching + graceful degradation is the "agentic" part.

- **Crawler Agent** (`crawler_agent.py`) — BFS crawl via Playwright, bounded
  by `max_pages`/`max_depth`. For every page it captures a screenshot,
  console errors, failed network requests, and a DOM inventory (forms,
  buttons, links, images) that later agents use to decide what to test.

- **Functional Test Agent** (`functional_agent.py`) — **generates** test
  cases from each page's actual DOM inventory (a page with 3 forms gets
  form tests for those 3 forms; a page with none gets zero), then executes
  them with Playwright: link reachability, broken images, empty-required-field
  form submission.

- **Accessibility Agent** (`accessibility_agent.py`) — injects real
  axe-core into every page and runs a full WCAG audit.

- **Bug Intelligence** (`bug_aggregator.py`) — merges functional failures,
  accessibility violations, console errors and network errors into a single
  deduplicated, severity-ranked bug list with a stated rationale per bug,
  plus an overall quality score.

- **Dashboard** (`frontend/index.html`) — single-page UI: start a scan,
  watch the live agent execution log (polls `/api/scan/{id}` every 1.5s),
  see the quality scoreboard and the bug explorer once the scan completes.

Nothing here is scoped to one demo site — `demo-site/` exists only to make
the demo reliable; the scanner logic makes no reference to it.

## Run it locally

```bash
# 1. Install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

# 2. Start the backend
uvicorn backend.main:app --reload --port 8000

# 3. Open the dashboard
#    Just open frontend/index.html in a browser (it talks to
#    http://localhost:8000 by default — change the API constant
#    at the top of index.html if you deploy the backend elsewhere).

# 4. (Optional) Serve the demo site to scan something with known bugs
python3 -m http.server 5500 --directory demo-site
# then scan http://localhost:5500 from the dashboard
```

## Try it against a real, unseen site

Paste any public URL (e.g. `https://example.com`, `https://your-project.com`)
into the dashboard and hit **Start Autonomous QA Scan**. Nothing needs to be
pre-configured for a new site — the Crawler discovers pages, the Functional
Agent generates tests from what it finds, and the Bug Intelligence agent
reports whatever bugs actually exist.

## API surface (Phase 1 subset of the full spec)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/scan` | Start a scan (`url`, `max_pages`, `max_depth`, `device`) |
| GET | `/api/scan/{id}` | Full scan state |
| GET | `/api/scan/{id}/status` | Lightweight polling endpoint |
| GET | `/api/scan/{id}/agents` | Agent execution log |
| GET | `/api/scan/{id}/bugs` | Bug list |
| GET | `/api/scan/{id}/screenshots` | Screenshot manifest |
| GET | `/api/scan/{id}/report` | Summary report |
| GET | `/health`, `/api/health` | Backend / browser / DB / LLM / RAG status |

## Known Phase 1 limitations (by design — see roadmap)

- State is **in-memory** (`SCANS` dict in `main.py`), not PostgreSQL yet.
- No LLM/RAG involved yet — severities and test generation are rule-based
  on real signals (axe impact, test category). Root cause explanations and
  WCAG-linked recommendations arrive in Phase 2.
- No Visual Regression, Performance, Security, Fix, or Verification agents
  yet.
- No WebSocket/SSE — the dashboard polls REST every 1.5s. Good enough for
  Phase 1, swap for SSE/WebSocket alongside the DB migration.
- Single scan runs sequentially in an `asyncio` background task; no
  Celery/Redis queue yet (fine for Phase 1 demo load).

## Next steps to build out Phase 2

1. **Add PostgreSQL** — create SQLAlchemy models mirroring `ScanState`
   (`Scan`, `Page`, `Bug`, `TestResult`, `Evidence`, …) and swap the
   `SCANS` in-memory dict for DB reads/writes. Keep `to_dict()` as the API
   contract so the frontend doesn't change.
2. **Wire in LangGraph** — replace the current linear
   `try/except`-chained Supervisor with a LangGraph `StateGraph` so the
   conditional edges (`IF accessibility issue → retrieve WCAG guidance`,
   `IF verification fails → retry`) are explicit graph edges rather than
   Python `if` statements. The `ScanState` dataclass becomes the graph
   state schema directly.
3. **RAG Agent** — stand up ChromaDB, chunk/embed WCAG + MDN + OWASP
   defensive docs (`knowledge_base/`), and give the Bug Intelligence agent
   a `retrieve(bug)` tool call so each bug gets grounded guidance instead
   of the current static rationale strings.
4. **Root Cause Agent** — an LLM call (Claude) that takes a bug + its
   evidence (DOM snippet, console error, screenshot) and produces a
   symptom → root cause → impact → confidence chain, replacing the
   current one-line `severity_rationale`.
5. **Visual Agent + Visual Regression** — add a vision-model pass over
   screenshots for overlap/clipping/overflow detection, and a
   baseline-vs-new screenshot diff pipeline (`Pillow`/`opencv` pixel diff +
   vision explanation).
6. **Performance & Security Agents** — Lighthouse (or
   `playwright`-collected navigation timing + resource sizes) and the safe
   header/cookie/mixed-content checks from spec section 14.
7. **Fix + Verification loop** — Fix Agent proposes a code-level fix
   (diff for source-connected mode, snippet for URL-only mode);
   Verification Agent re-runs the relevant test; Supervisor retries up to
   3x per spec section 17.
8. **Real-time UI** — swap dashboard polling for SSE (`/api/scan/{id}/stream`)
   fed by the Supervisor's `state.log()` calls.
9. **Dockerize** — split into `frontend`, `backend`, and a
   Playwright-capable `browser-worker` service per spec section 29, with
   `docker-compose.yml` wiring them + Postgres + Chroma together.
10. **Automated tests** — pytest suite for the Supervisor's conditional
    branches (crawl-fails → abort; functional-fails → continue with
    warning), bug dedup logic, and an E2E test against `demo-site/`.

## Project structure

```
webguardian-ai/
├── backend/
│   ├── agents/
│   │   ├── state.py            # shared ScanState
│   │   ├── supervisor.py       # orchestrator + conditional logic
│   │   ├── crawler_agent.py
│   │   ├── functional_agent.py
│   │   ├── accessibility_agent.py
│   │   └── bug_aggregator.py
│   └── main.py                 # FastAPI app
├── frontend/
│   └── index.html              # single-page dashboard
├── demo-site/
│   └── index.html              # local site with intentional bugs
├── requirements.txt
├── .env.example
└── README.md
```
