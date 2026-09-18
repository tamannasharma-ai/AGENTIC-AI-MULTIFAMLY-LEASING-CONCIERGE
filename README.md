# Multifamily Leasing Concierge

A fictional, single-community Streamlit demo with LangGraph, Groq, PostgreSQL and local MiniLM policy embeddings. Inventory and policies are sample data; photos are illustrative. Do not use this prototype for actual leasing decisions without further review.

## Run locally

Use Python 3.12+ and a virtual environment. Dependencies are pinned to the versions in the development environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Configure `.env` using the key names in `.env.example`. Keep it private. Use an existing PostgreSQL/Supabase database with pgvector and a Groq account on its free plan. Never enable paid usage to run this demo. Hosted free plans have quotas and may suspend idle projects; the app cannot enforce account billing settings.

For a new demo database, run these commands once:

```powershell
.\.venv\Scripts\python.exe db_schema.py
.\.venv\Scripts\python.exe seed_demo_inventory.py
.\.venv\Scripts\python.exe seed_kb.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The schema initializer creates tables and pgvector, including available_from. Existing databases must have compatible UUID primary keys. The curated seed reproduces 72 varied fictional units and only inserts missing units. The optional CSV importer also only inserts missing units: neither overwrites curated data, unit IDs, statuses, bookings or holds. MiniLM downloads its weights the first time it is used, then runs on CPU.

## Behavior

- Complete tool messages persist for the browser session; clearing the conversation does not cancel bookings or holds.
- Tours default to America/Chicago and respect explicit supported time zones or ISO offsets. Ambiguous times require clarification. Tours last 45 minutes, Monday-Saturday, with starts every 15 minutes from 10 AM through 5:15 PM and at least two hours notice. A held unit requires its full hold reference and matching email for a tour.
- Search supports unit number, specials-only, page and page size, with total match counts. No silent five-result inventory limit.
- Factual tool-backed replies are rendered from the tool evidence. The evaluator replaces model prose using the same message ID; rejected answers do not remain in chat.
- Database locks serialize tour booking and unit holds. Expiry cleanup runs during inventory and booking requests; it preserves newer active holds. The timer uses the stored expiry timestamp.
- Calendar downloads remain available after reruns. Email is optional; failure does not cancel a confirmed tour. The Resend default sender is limited to its permitted test recipients; omit its key for a no-email demo.
- The contact form requires consent. Policy embeddings are cached once per process. Guard service outages allow ordinary conversation to continue; prompt checks are not a compliance guarantee.
- OpenStreetMap is embedded with attribution. No paid maps or geocoding key is required.

## Tests

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Tests use mocked external services and do not send email or change your database. `test_db.py` is a separate manual connection diagnostic, excluded from test collection. `sample.py` contains a product document rather than executable Python.

For the opt-in PostgreSQL integration check, run `python tests/integration_check.py`. It creates a temporary schema inside a transaction, exercises booking/hold/search SQL, and rolls all test changes back. Email is mocked. It needs schema-creation privileges on the configured database.

`python tests/analytics_integration_check.py` similarly verifies analytics migrations, idempotent writes, feedback edits/removal and mode separation inside a rolled-back temporary schema.

## Optional market context

`rentcast_sync_worker.py` runs once by default and updates only `market_comps`. It never replaces community inventory. Leave RentCast disabled to avoid any external data quota or billing concerns. No scheduler is enabled automatically. If using an existing free account, run it manually within that account's quota; `--schedule` keeps a local process running weekly.

## Success metrics

Analytics uses the existing PostgreSQL database and installed Streamlit/Pandas libraries. No additional analytics service, API key, paid dependency or AI evaluation call is used.

Apply the additive schema migration and start the separate staff dashboard:

```powershell
.\.venv\Scripts\python.exe -B db_schema.py
.\.venv\Scripts\python.exe -B -m streamlit run metrics_app.py --server.address 127.0.0.1 --server.port 8503 --server.headless true --browser.gatherUsageStats false
```

`ANALYTICS_ENABLED=true` enables tracking; set it to `false` to opt out. `ANALYTICS_MODE=demo` is the default for this fictional community. Only use `live` for a deliberately configured real deployment. Tests disable writes by default and use `test` mode when mocking analytics. Changing modes affects new requests only; historical traffic is not relabelled. Dashboard filters never combine modes.

The dashboard refuses to load on a non-loopback listener. Do not put this local port behind a public proxy or tunnel. Public hosting requires real staff authentication and authorization first. It is intentionally not an unauthenticated page in the leasing portal. Analytics tables have PostgreSQL row-level security enabled without public-client policies; use the existing trusted server database connection, never browser credentials.

Tracked measures:

- Requests and random browser sessions, separated into typed chat, suggested prompts, inventory and consented contact forms.
- Tool-backed request completion: every invoked tool must have a known successful result. Valid no-match inventory/availability results count; missing policy evidence, validation rejections, technical failures, unfinished turns and ordinary replies do not. This is an operational proxy, not independently audited task accuracy.
- Per-task/source tool attempt counts and completion rates, plus suggested-prompt clicks and completed requests. Compare sources within the same task category; this is not a randomized experiment. Suggestion indices in `chat_suggestions.py` must remain stable.
- Search-to-tour conversion: distinct sessions with a recorded search attempt and a later confirmed booking inside the selected window, divided by searching sessions. Repeated tours do not inflate conversion. These are sessions, not unique prospects; cross-session and out-of-window conversions are not attributed.
- Median/p95 processing seconds with sample counts, separated by source. Includes failures; excludes telemetry writes and browser rendering. This is not time to first useful content on screen.
- Technical error categories, unfinished requests, daily outcomes, and median chat turns per session. Unfinished is not automatically abandonment; a booking may have committed before an interrupted request or lost telemetry.
- Optional one-to-five-star helpfulness ratings on the latest chat reply, rating counts and coverage. Revising a rating replaces it; clearing it removes it. Rating cohorts use the original request date.

`analytics_events` stores random session/request IDs, fixed categorical outcomes, timestamps, processing durations, suggestion indices, ratings and confirmed tour/hold IDs. It never stores prompts, replies, tool payloads, names, emails, IP addresses or contact fields. Tour/hold IDs are linkable by authorized staff, so treat these as pseudonymous operational records, not fully anonymous data. Existing booking/contact records are unchanged. The new tracker does not use the legacy transcript-oriented `rag_eval_metrics` table.

Writes have short connection/statement timeouts and fail without undoing leasing actions. Failed telemetry is logged without exception details; statistics are based only on recorded activity and are not a lossless business ledger. Reruns have stable event IDs, and finished requests cannot be overwritten by stale start events. Data is retained until explicitly removed by the database owner; choose a retention period appropriate to the deployment and monitor storage quotas. The dashboard limits each query to 50,000 events and asks for a shorter period rather than silently truncating.

Independent answer accuracy, attendance, applications, leases, and production booking integrity are marked not yet measured. They require reviewed test cases or actual business outcome tracking; the app does not fabricate values. Suggested demo acceptance goals remain >=95% audited scenarios completed, 100% critical facts correct in the test set, zero invalid writes in retry/concurrency tests, and mean helpfulness >=4/5 with its sample size. These are proposed targets, not industry benchmarks or achieved results.

## Interview demo

For the local presenter controls, explicitly enable demo mode and bind the server to loopback:

```powershell
$env:DEMO_CONTROLS = "true"
$env:ANALYTICS_MODE = "demo"
.\.venv\Scripts\python.exe -B -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

- Chat consumes LangGraph `messages` token events alongside `values` snapshots. Live output is labelled as an unchecked draft; the completed evaluator reply replaces it before analytics writes. Drafts can contain inaccuracies before evaluation, so do not treat them as final availability, prices or booking confirmations. No artificial typing delay or extra model call is used. Tool arguments/reasoning blocks are not rendered as reply text, and separate graph steps/fallback attempts do not get concatenated.
- Reply captions show total processing time across guardrails, tools, failed attempts and evaluation, plus the actual serving model. The model routes/generates the draft; factual final prose can be replaced by the deterministic evaluator. A guardrail refusal is not attributed to a model. This timing excludes analytics writes and browser paint.
- **Reset demo** clears the current conversation/results, expires already-stale holds, and clears policy/market caches. It does not cancel active holds, pending reservations, confirmed reservations or tours, and it does not delete analytics. The backend repeats the demo/local checks. This is cleanup, not a destructive database reseed.
- The presenter sidebar shows blocked prompts, average helpfulness with sample size, and fallback-trigger rate for demo traffic over the past 24 hours. Metrics refresh on demand or after a 30-second cache TTL. The fallback denominator includes only requests with recorded model attempts; older records and guardrail-only requests are not silently treated as primary successes. Both attempted and successful fallbacks count as triggers.
- The read-only **How this works** diagram follows the implemented guardrail/agent/tools/evaluator graph. It is generated from this project's architecture, not a copied portfolio image.
- Policy/embedding lookup results and market summaries cache for five minutes, bounded to 256 and 32 keys respectively. Inventory, tour availability, holds, bookings and lead writes remain uncached. Policy/market edits can take up to five minutes to appear unless the presenter resets the read caches.
- All chat/search/consented-contact submissions share a limit of ten requests per minute per browser session. Ordinary rerenders do not consume a slot, and clearing/resetting the conversation does not remove the limit. This is a lightweight quota guard, not abuse protection: new sessions, other processes and direct tool calls can bypass it.

Keep `DEMO_CONTROLS=false` for public hosting. Never expose the presenter server through a public proxy/tunnel without real staff authentication; a loopback listener is not authentication against a proxy. No email hash is needed for the new analytics because emails are omitted entirely, including in failure logs.

The GitHub Actions workflow in `.github/workflows/tests.yml` runs the unit/UI suite on push and pull requests, with read-only repository permissions, no service secrets and a ten-minute job timeout. `requirements-ci.txt` installs only test-needed packages, avoiding embedding-model downloads. It starts running only after this project is pushed to GitHub with Actions enabled. Local tests do not prove a hosted workflow run has passed. Standard GitHub-hosted runners remain subject to the account's included usage and billing settings; do not enable paid overages for this demo. See the [official Python workflow guide](https://docs.github.com/en/actions/tutorials/build-and-test-code/python).

## Hosting

The app can run locally at no hosting cost. For a hosted demo, configure the same keys in Streamlit secrets on a free Community Cloud account, subject to its current resource limits. MiniLM can be memory-intensive on small instances. Secrets and contact details should never be committed.

Model IDs are configurable; check the [Groq model catalog](https://console.groq.com/docs/models) when changing them. No paid fallback provider is configured.

The default primary is `qwen/qwen3.8-27b`; the fallback is `openai/gpt-oss-20b`, both verified in the account's model catalog on September 18, 2026. The fallback must support custom function calling: [Groq Compound does not support user-provided tools](https://console.groq.com/docs/compound). Qwen reasoning is requested separately from answer text, so internal reasoning is not displayed as a streamed reply. Availability and free-plan limits can change; environment overrides remain supported.

Remaining production work includes authentication, durable chat storage, cancellation flows and load testing. Tool-backed answers use deterministic rendering; arbitrary conversational prose is not a general semantic fact-checking system.

`reconcile_demo_records.py` backs up and repairs legacy expired pending reservations and conflicting/out-of-hours demo tours. Run only for this fictional demo. It retains record IDs and contacts, and sends no notifications. `seed_kb.py` backs up existing policies and updates all eight categories using local embeddings.
