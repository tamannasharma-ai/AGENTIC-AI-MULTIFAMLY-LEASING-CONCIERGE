# Multifamily Leasing Concierge

A fictional, single-community Streamlit demo with LangGraph, Groq, PostgreSQL and local MiniLM policy embeddings. Inventory and policies are sample data; photos are illustrative. Do not use this prototype for actual leasing decisions without further review.

The demo represents **The Standard Residences**, at the fictional community address **1001 Julia St, New Orleans, LA 70113**. Prospects can discover apartments, compare costs, ask policy questions, schedule tours, place temporary holds and request follow-up. A separate local dashboard reports operational metrics.

## Contents

- [Features and usage](#features-and-usage)
- [Run locally](#run-locally)
- [Configuration](#configuration)
- [Architecture and project files](#architecture-and-project-files)
- [Behavior](#behavior)
- [Tests](#tests)
- [Optional market context](#optional-market-context)
- [Success metrics](#success-metrics)
- [Interview demo](#interview-demo)
- [Apartment decision tools](#apartment-decision-tools)
- [Hosting](#hosting)
- [Maintenance and troubleshooting](#maintenance-and-troubleshooting)

## Features and usage

### Concierge chat and conversation history

Use the **Concierge** tab to describe your apartment requirements or ask questions in natural language. Suggested questions cover studios, two-bedroom homes, move-in specials, pets, applications and tour availability. Search replies include apartment cards with rent, bedrooms, bathrooms, square footage, recorded amenities, illustrative photos and available promotions.

The sidebar lets you start a **New chat**, switch between **Recent conversations**, or **Clear conversation**. Conversations retain messages, tool results and feedback context for the current browser session; their titles come from the first user message. The shortlist, request limit and analytics session remain shared across conversations. Clearing a chat does not cancel database records.

Replies stream as unchecked drafts before the final evaluated answer replaces them. Completed replies show processing time and serving-model information where available. With analytics enabled, you can rate the latest reply from one to five stars, revise the rating or remove it.

### Available homes and amenity matching

The **Available Homes** tab provides a structured search without requiring a chat prompt:

- Filter by bedroom count, maximum monthly rent, exact unit number and move-in specials. A rent limit of `0` in the form means no maximum.
- Choose must-have and nice-to-have amenities: central air conditioning, dishwasher, in-unit laundry, walk-in closet, patio, balcony and corner unit.
- Must-haves exclude homes lacking the recorded feature. Nice-to-haves rank matching homes ahead of others, followed by lower rent and unit number.
- Browse result pages and see total matches. The form uses five homes per page; the chat search tool supports page sizes from 1 to 25.
- Expand **Why this home?** for an explanation based on your selected budget and features.
- If the first page has no matches, select **Check one-change alternatives** and explicitly accept a proposed budget or amenity change to search again.

Search includes only vacant units whose availability date has arrived or is unspecified. Demo promotions are calculated from vacancy age: at least 45 days gives $500 off the first month's rent; at least 60 days gives $750 off plus a waived $100 admin fee. The calculator does not automatically apply these promotions.

### Shortlist and move-in cost comparison

Save up to three homes from inventory or chat cards, then open **Shortlist** to compare rent, size, bedrooms, bathrooms, amenities and unconfirmed specials. Remove homes at any time or use **Ask about these homes** to request a fresh chat comparison.

The cost form accepts the number of adult applicants, pets, a 6- or 12-month lease, parking type (none, surface, garage or EV) and parking spaces. **Refresh availability and calculate** checks current database records and policy documents, then displays known monthly costs, first-month costs, individual fees and deposits, source policies and the check timestamp. Missing or conflicting policy information is shown as unknown. Saving or estimating a home does not reserve it. See [Apartment decision tools](#apartment-decision-tools) for calculation limits.

### Property policies and application guidance

Ask the concierge about eight seeded policy categories: pets; parking and storage; lease terms and applications; utilities and trash; office hours; amenity hours; packages and guests; and move-in fees. Local MiniLM embeddings and PostgreSQL vector search retrieve written policy evidence. If no sufficiently relevant policy is found, the app directs the prospect to the leasing office.

Application answers explain the sample requirements and fees. The app does not submit applications, screen applicants, collect payments or execute leases.

### Tour availability, booking and calendar invitations

Ask for available tour times, optionally for a specific unit. The concierge returns up to eight open slots over the next two weeks. To book, provide a unit number, name, email, date/time and tour type: **in-person**, **self-guided** or **virtual**. The app records the tour type; it does not provision a video meeting or self-guided access code.

Tours last 45 minutes, require at least two hours' notice and start Monday through Saturday on 15-minute boundaries between 10:00 AM and 5:15 PM Central. The schedule prevents overlapping tours across the community. Times such as “tomorrow at 2 PM” are supported; ambiguous requests need clarification. A held unit requires its full reservation reference and the matching email.

After confirmation, download an `.ics` invitation using **Add to calendar**. Optional Resend email delivery is attempted after the booking commits; an email failure leaves the booking intact. Calendar downloads remain accessible in the session's chat history.

### Temporary apartment holds

Ask the concierge to hold a vacant unit and supply a name and email. A successful request creates an exclusive **15-minute VIP hold**, changes the unit's status to held and displays a countdown based on the saved expiry time. Database locking protects concurrent hold requests. Expired holds are cleaned up during inventory and booking-related requests; the countdown alone does not run a background cleanup job.

A hold is temporary and is not a signed lease or paid reservation. There is no user-facing cancellation or permanent reservation-confirmation flow.

### Contact requests and location

The **Contact** tab collects a name, email, optional phone number, preferred bedroom count and monthly budget. Saving requires the contact-consent checkbox. Records are created or updated by email, and the concierge also exposes a lead-capture tool for conversational follow-up. This stores a lead in PostgreSQL; it does not automatically send a message to a leasing employee or integrate with an external CRM.

The **Location** tab shows office hours, an OpenStreetMap embed and an **Open map** link. The virtual concierge can answer questions and book future tours outside office hours.

### Market context, guardrails and presenter tools

Optional market comparisons summarize stored nearby rental data by bedroom count, including average, minimum and maximum rents and sample counts. They are separate from community availability and require the optional RentCast import described below.

Chat requests pass through local fair-housing topic checks and a Groq prompt-attack check before agent execution. Tool-backed facts are rendered from tool evidence by the evaluator. These checks have limits: guard-service failures permit ordinary conversation to continue, and arbitrary conversational prose is not comprehensively fact-checked.

Local presenter controls provide a safe demo reset, recent aggregate metrics and a blocked-prompt example. The sidebar also includes **How this works**. See [Interview demo](#interview-demo) and [Success metrics](#success-metrics) for enabling these features and interpreting the measurements.

## Run locally

Use Python 3.12+ and a virtual environment. Dependencies are pinned to the versions in the development environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If `.env` does not already exist, copy the example and fill in your credentials:

```powershell
Copy-Item .env.example .env
```

Keep `.env` private. Use an existing PostgreSQL/Supabase database with pgvector and a Groq account on its free plan. Never enable paid usage to run this demo. Hosted free plans have quotas and may suspend idle projects; the app cannot enforce account billing settings.

For a new demo database, run these commands once:

```powershell
.\.venv\Scripts\python.exe db_schema.py
.\.venv\Scripts\python.exe seed_demo_inventory.py
.\.venv\Scripts\python.exe seed_kb.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The schema initializer creates tables and pgvector, including available_from. Existing databases must have compatible UUID primary keys. The curated seed reproduces 72 varied fictional units and only inserts missing units. The optional CSV importer also only inserts missing units: neither overwrites curated data, unit IDs, statuses, bookings or holds. MiniLM downloads its weights the first time it is used, then runs on CPU.

Open the local URL printed by Streamlit, normally `http://localhost:8501`. Run commands from the repository root. For runtime-only installation, use `requirements.txt`; `requirements-dev.txt` also installs pytest.

## Configuration

The supported `.env` keys are:

- `SUPABASE_DB_URL`: PostgreSQL connection string used by the app, schema tools, seed scripts and analytics. Use a trusted server connection with the required table permissions; initial setup also needs permission to create the vector extension and tables.
- `GROQ_API_KEY`: enables conversational requests, model tool calling and the remote prompt guard. Without it, chat controls are disabled; database-backed inventory, contact and shortlist features can still be used.
- `GROQ_MODEL`: primary chat model; the configured code default is `qwen/qwen3.8-27b`.
- `GROQ_FALLBACK_MODEL`: fallback model; the configured code default is `openai/gpt-oss-20b`. Model availability depends on the account. Both chat models must support the app's tool calls.
- `RESEND_API_KEY`: optional tour-confirmation email delivery. Leave blank to use calendar downloads without email.
- `RENTCAST_API_KEY`: optional standalone market-data worker credential. It is not needed for apartment search or booking.
- `ANALYTICS_ENABLED`: defaults to `true`; set to `false` to disable operational tracking.
- `ANALYTICS_MODE`: `demo`, `live` or `test`; keep this fictional community on `demo`.
- `DEMO_CONTROLS`: enables presenter controls only with `ANALYTICS_MODE=demo` and an explicit loopback listener. The code defaults to `false`, while `.env.example` sets it to `true` for local demos; set it to `false` for public hosting.

The main app also loads its supported settings from Streamlit secrets when they are not already set in the environment. Standalone database scripts, the market worker and the metrics app use environment variables or `.env`.

## Architecture and project files

The request flow is **Streamlit → guardrail → LangGraph agent → tools → agent → evaluator → final reply**. The agent can make multiple tool calls before completing a response. Groq supplies the primary/fallback language models; local MiniLM supplies policy embeddings; PostgreSQL stores business records and analytics. Inventory forms and the cost calculator call their data helpers directly.

- `app.py`, `chat_theme.css`: main five-tab portal, chat rendering, apartment cards, forms and styling.
- `agent3.py`: LangGraph workflow, model fallback, guardrails and seven tools: `search_vacant_units`, `lookup_property_policy`, `lookup_market_comps`, `list_tour_availability`, `book_tour_appointment`, `create_reservation_hold` and `capture_prospect_lead`.
- `grounded_replies.py`: evidence-based final rendering of tool results.
- `leasing_utils.py`: property constants, date/time validation, tour collisions, calendar generation, demo specials and map helpers.
- `conversation_state.py`, `chat_suggestions.py`: browser-session conversations and stable suggested-question definitions.
- `home_matching.py`: amenity matching explanations and explicit one-change alternatives.
- `choice_ui.py`, `home_choices.py`: shortlist UI, current-record retrieval and policy-based cost calculations.
- `demo_features.py`: presenter gating, request throttling, streaming helpers and architecture diagram.
- `leasing_analytics.py`, `metrics_app.py`: operational event tracking, aggregation and the separate staff dashboard.
- `db_schema.py`, `seed_demo_inventory.py`, `seed_kb.py`: schema initialization and fictional inventory/policy setup.
- `ingest_dataset.py`, `diversify_demo_inventory.py`, `reconcile_demo_records.py`: optional import and legacy-demo maintenance utilities.
- `rentcast_sync_worker.py`: optional one-time or scheduled market-data import.
- `tests/`, `pytest.ini`, `.github/workflows/tests.yml`: automated tests, integration diagnostics and CI configuration.
- `PRD.html`, `docs/index.html`, `sample.py`: supporting product/demo documents; `sample.py` is not executable Python.
- `Redesign Chat Box/`: separate React/Vite design project, not required to run the Streamlit portal. `oldversions/` contains earlier app versions.

Core database tables are `units` (inventory), `property_knowledge` (policy text and 384-dimensional embeddings), `tours` (appointments), `reservations` (temporary holds), `leads` (contact details), `market_comps` (external market snapshots) and `analytics_events` (operational telemetry). Chat history and shortlists live in browser-session state rather than durable database storage.

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

## Apartment Decision Tools

- Inventory search supports explicit must-have amenities and nice-to-haves. Required features filter in SQL before pagination; preferences rank results by recorded feature matches, then rent and unit number. **Why this home?** explains budget and amenity matches without demographic inference or invented confidence scores.
- After an empty first-page search, **Check one-change alternatives** probes a higher rent limit or removal of one required amenity. Each probe retains bedroom, specific-unit and specials constraints. The cheapest candidate for each change is shown; multiple-change compromises are not searched. **Accept change and search** updates the visible filters and checks inventory again. Alternatives never silently change a search or book anything. Probe requests are read-oriented inventory lookups and share one session rate-limit slot per alternatives check; individual probes are not separately tracked in analytics.

- Save up to three homes from inventory or chat results in the session-only **Shortlist** tab. Removing a home invalidates the last cost snapshot. Saved search results are explicitly labelled as potentially outdated.
- **Refresh availability and calculate** reads current unit records and policy documents from PostgreSQL, without an LLM call or booking/hold write. It shares the session request limit. Unavailable or missing homes do not receive estimates; failed refreshes discard old estimates.
- Estimates separate recurring charges, one-time fees and refundable deposits. The first-month subtotal assumes a full month, includes the selected lease/parking options and excludes unknown usage charges. Discounts and admin waivers are not automatically applied. The pet-deposit basis is ambiguous in the current policy and requires confirmation.
- `home_choices.SUPPORTED_POLICIES` recognizes complete policy documents, not isolated dollar amounts. Changed, missing or duplicated policies produce unknown charges. When approved policy wording changes, update the matching cost rules and tests together. Source documents and the read timestamp appear with the estimate.
- Contextual buttons open comparison or submit read-only tour/policy questions through the existing guarded chat path. They never directly create reservations or contact records. These dynamic prompts use the existing typed-chat analytics category; shortlist clicks and calculator runs are not yet separate conversion events.
- Uses the existing dependencies and database; no additional subscription or API key. Session shortlists are not durable across reconnects.

## Hosting

The app can run locally at no hosting cost. For a hosted demo, configure the same keys in Streamlit secrets on a free Community Cloud account, subject to its current resource limits. MiniLM can be memory-intensive on small instances. Secrets and contact details should never be committed.

Model IDs are configurable; check the [Groq model catalog](https://console.groq.com/docs/models) when changing them. No paid fallback provider is configured.

The default primary is `qwen/qwen3.8-27b`; the fallback is `openai/gpt-oss-20b`, both verified in the account's model catalog on September 18, 2026. The fallback must support custom function calling: [Groq Compound does not support user-provided tools](https://console.groq.com/docs/compound). Qwen reasoning is requested separately from answer text, so internal reasoning is not displayed as a streamed reply. Availability and free-plan limits can change; environment overrides remain supported.

Remaining production work includes authentication, durable chat storage, cancellation flows and load testing. Tool-backed answers use deterministic rendering; arbitrary conversational prose is not a general semantic fact-checking system.

`reconcile_demo_records.py` backs up and repairs legacy expired pending reservations and conflicting/out-of-hours demo tours. Run only for this fictional demo. It retains record IDs and contacts, and sends no notifications. `seed_kb.py` backs up existing policies and updates all eight categories using local embeddings.

## Maintenance and troubleshooting

Maintenance scripts operate on the database configured in `SUPABASE_DB_URL`:

- Run `db_schema.py` after schema changes to apply the additive, repeatable setup.
- Run `seed_demo_inventory.py` to insert missing curated units. It does not restore modified units or cancel existing activity.
- Run `seed_kb.py` to back up and replace the eight supported policy categories. When changing policy wording, update the cost rules and their tests as described above.
- `ingest_dataset.py` expects `apartments_for_rent_classified_10K.csv` in the working directory. It cleans and filters source rows, takes up to 60 and inserts missing demo units. The curated seed is sufficient for normal setup.
- `diversify_demo_inventory.py` backs up and enriches legacy 400-square-foot demo rows in the first five floors, preserving unit identity and status.
- `reconcile_demo_records.py` can expire old records and reschedule conflicting demo appointments. Review the configured database before using it; it changes business records and sends no notifications.
- Run `python rentcast_sync_worker.py` for a single optional market refresh, or `python rentcast_sync_worker.py --schedule` to refresh immediately and keep a local worker running for Sunday at 03:00 local time. Stop that process to stop scheduling.

Common issues:

- **Database connection or missing-table errors:** verify `SUPABASE_DB_URL`, database reachability and permissions, then run the schema initializer. `test_db.py` is an optional manual connection diagnostic.
- **Chat is disabled:** set `GROQ_API_KEY` and restart the app. If model requests fail, check account access, quota and the configured tool-capable model IDs.
- **Policy lookup is slow on first use:** MiniLM downloads its model weights on first use. Allow network access for that initial download and enough local memory for the embedding model.
- **No homes match:** check rent, bedrooms, must-haves and the page number; held, leased and future-availability units are excluded. Try the explicit alternatives workflow.
- **An estimate shows unknown charges:** refresh the shortlist and check the source policy documents. Missing, changed or duplicate policies deliberately prevent unsupported calculations.
- **A tour was booked but no email arrived:** use the calendar download and verify Resend configuration and allowed recipients. Do not repeat a successful booking just to retry email.
- **Presenter controls are missing or metrics refuse to load:** use the explicit `127.0.0.1` launch commands above. Presenter controls additionally require demo mode and `DEMO_CONTROLS=true`.
- **A request was interrupted:** check existing records before retrying a booking or hold; a database write may have committed before the UI received its result.
- **The request limit is reached:** wait for the displayed retry interval. Starting or clearing a conversation does not reset the session limit.
