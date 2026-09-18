# Product Requirements Document (PRD)

**Product Name:** Autonomous AI Virtual Leasing Concierge

**Target Domain:** Multi-Family PropTech & Residential Asset Operations

**Architecture:** Multi-Tenant Autonomous Agent Architecture

**Status:** In Active Production / Staging

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement

In traditional multifamily operations, the lead-to-tour pipeline suffers from friction, high labor overhead, and missed conversion windows:

* **Off-Hour Abandonment:** Over 45% of renter inquiries arrive outside standard leasing office hours (5 PM – 9 AM). Static contact forms result in prolonged response latency and lead decay.
* **Double-Booking & Staff Friction:** On-site leasing teams manage appointments manually across fragmented channels, creating tour schedule collisions and double-booking errors.
* **Stale Vacancy Costs:** Stale inventory (vacancies exceeding 45 days) consumes unrecovered carrying costs. On-site leasing agents frequently lack deterministic systems to dynamically offer pre-approved concessions without manual manager sign-offs.
* **Compliance Exposure:** Manual leasing communication risks non-compliance with the U.S. Fair Housing Act when staff face subjective prospect inquiries regarding neighborhood safety, crime statistics, or local demographics.

### 1.2 Solution Vision

The Autonomous AI Virtual Leasing Concierge is an enterprise-grade, multi-tenant digital leasing platform. Built with **LangGraph**, **Groq (Qwen)**, **Supabase (PostgreSQL + pgvector)**, and a **Streamlit** split-screen interface, it automates the renter acquisition funnel:

1. Surfaces real-time vacant inventory with dynamic move-in concessions for units vacant $\ge 45$ days.
2. Resolves policy inquiries using semantic RAG retrieval while adhering to Fair Housing Act guidelines.
3. Coordinates tour bookings with conflict detection (45-minute collision buffers) and transactional email confirmations via Resend.
4. Executes temporary 15-minute "VIP Holds" directly in the operational database with live countdown timers, taking units off the open market without requiring immediate external payment processing.

---

## 2. Personas & Target Users

| Persona | Role | Core Jobs-to-be-Done | Key Pain Points |
| --- | --- | --- | --- |
| **The Prospect (Renter)** | High-intent apartment hunter | Search available layouts, view unit media, verify pet/parking costs, book private tours, lock in promotional pricing. | Outdated availability feeds, hidden ancillary fees, delayed tour confirmations. |
| **Leasing Specialist / Agent** | On-site property representative | Conduct verified in-person tours, receive pre-qualified lead dossiers, maintain clean tour calendars. | Manual calendar juggling, fielding repetitive policy questions, unvetted leads. |
| **Property Manager / Asset Director** | Operational portfolio lead | Accelerate time-to-lease, reduce operational vacancy days, enforce pricing and policy compliance. | Revenue leakage from long vacancy durations, Fair Housing liability exposure. |

---

## 3. System Architecture & Technical Specifications

```
  ┌────────────────────────────────────────────────────────┐
  │         Streamlit Luxury Split-Screen Interface         │
  │   [Left: Property Showcase]  [Right: Concierge Window]  │
  └───────────────────────────┬────────────────────────────┘
                              │ Active User Queries / Prompt Chips
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │          LangGraph Orchestration State Machine         │
  │              Model: Groq (Qwen 3.8 27B)                │
  │              Compliance: Fair Housing System Guard     │
  └─────────────┬───────────────────────────┬──────────────┘
                │ Tools Execution           │ Semantic Query
                ▼                           ▼
  ┌───────────────────────────┐   ┌────────────────────────┐
  │ PostgreSQL Primary DB     │   │ pgvector Store         │
  │ - units (w/ vacant_since) │   │ - property_knowledge   │
  │ - tours (w/ buffer index) │   │ - MiniLM-L6-v2 vectors │
  │ - reservations (15m hold) │   └────────────────────────┘
  │ - leads (CRM upserts)     │
  └─────────────┬─────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
┌──────────────┐  ┌──────────────┐
│  Resend API  │  │ RentCast API │
│ Email Engine │  │ Sync Worker  │
└──────────────┘  └──────────────┘

```

### 3.1 Technology Stack

* **Agent Framework:** LangGraph (StateGraph with conditional edge routing to prebuilt ToolNodes).
* **LLM Engine:** Groq Cloud API serving `qwen/qwen3.8-27b` at low latency ($<600\text{ ms}$ TTFT).
* **Primary Database:** Supabase Managed PostgreSQL.
* **Vector Store:** Supabase `pgvector` with `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional embeddings).
* **Application Frontend:** Streamlit with custom CSS (glassmorphism design system, persistent split-screen layout, and HTML5/JS embedded components).
* **Communication Gateway:** Resend API for transactional, branded HTML email confirmations.
* **Data Integration:** RentCast API integration with scheduled automated ingest pipelines.
* **Background Processing:** APScheduler executing daily/twice-weekly data sync workers.

---

## 4. Functional Requirements & Feature Scope

### Feature Module 1: Inventory Search & Dynamic Concession Engine

* **FR-1.1:** The system shall expose a tool `search_vacant_units(max_rent, bedrooms)` querying Supabase for units where `status = 'vacant'`.
* **FR-1.2:** The query shall dynamically calculate `days_vacant` via SQL:

$$\text{days\_vacant} = \text{EXTRACT(DAY FROM (NOW() - COALESCE(vacant\_since, NOW())))::int}$$


* **FR-1.3:** Concession rules must attach promotional metadata dynamically:
* $\ge 45\text{ days}$: Attaches `"Move-in Special: $500 off 1st month's rent!"`.
* $\ge 60\text{ days}$: Attaches `"Special Promotion: $750 off 1st month's rent + Waived $100 Admin Fee!"`.
* $< 45\text{ days}$: Returns `special_offer = None`.


* **FR-1.4:** The agent shall proactively pitch authorized concessions in conversational prose and highlight them via gold badge components (`.concession-pill`) in the UI.

### Feature Module 2: Strict Anti-Collision Tour Scheduling Engine

* **FR-2.1:** The system shall expose `book_tour_appointment(unit_number, prospect_name, prospect_email, date_time, tour_type)`.
* **FR-2.2:** Tour booking must verify that the target unit is strictly `vacant`. If the unit is `held`, `reserved`, or `leased`, the appointment must be refused.
* **FR-2.3 (Collision Prevention):** The tool must query existing appointments in `tours` to enforce a mandatory 45-minute collision buffer:
```sql
SELECT id, scheduled_at FROM tours 
WHERE scheduled_at >= (%s::timestamptz - INTERVAL '44 minutes')
  AND scheduled_at <= (%s::timestamptz + INTERVAL '44 minutes')
LIMIT 1;

```


If a conflict exists, the tool rejects the booking, states the conflicting time, and prompts the prospect to pick an adjacent open slot.
* **FR-2.4:** On successful booking, the system dispatches a branded HTML email via Resend containing the prospect name, unit number, timestamp, visitor parking guidelines, and unique tour UUID.

### Feature Module 3: VIP Rate Lock & Temporary Reservation Holds

* **FR-3.1:** The system shall expose `create_reservation_hold(unit_number, prospect_name, prospect_email)`.
* **FR-3.2:** Execution sets the unit status in `units` to `'held'` and inserts a record in `reservations` with status `'held'` and an expiration timestamp:

$$\text{expires\_at} = \text{NOW()}_{\text{UTC}} + 15\text{ minutes}$$


* **FR-3.3:** The agent emits a structured delimiter payload:
`VIP_HOLD_INITIALIZED::{"unit_number": "...", "expires_at": "...", "seconds_remaining": 900}::[Message]`
* **FR-3.4:** The frontend parses this payload and renders a live, pulsing JavaScript countdown banner (`render_vip_countdown_banner`) that updates seconds in real time.
* **FR-3.5:** Expired holds without finalized leases revert to `'vacant'` via database trigger or cleanup tasks.

### Feature Module 4: Compliance-Guarded Knowledge Base (RAG)

* **FR-4.1:** The system shall expose `lookup_property_policy(query)` executing vector cosine similarity search against `property_knowledge`.
* **FR-4.2 (Fair Housing Mandate):** System instructions mandate adherence to the U.S. Fair Housing Act. The agent must systematically refuse to answer subjective inquiries regarding:
* Neighborhood crime or safety statistics.
* Racial, ethnic, or demographic makeups.
* Local religious institutions or familial status distribution.


* **FR-4.3:** The mandatory fallback response must state:
> *"Under Fair Housing guidelines, I cannot comment on neighborhood demographics or safety. I can, however, provide official floor plans, unit specs, pricing, and tour scheduling."*



### Feature Module 5: Automated Market Ingestion & Local Backups

* **FR-5.1:** A dedicated background worker (`rentcast_sync_worker.py`) using `APScheduler` executes scheduled pulls of long-term apartment listings.
* **FR-5.2:** Data is pulled via RentCast REST API (`/v1/listings/rental/long-term`) within API limits.
* **FR-5.3:** Each pull outputs a timestamped local CSV snapshot (`rentcast_daily_dumps/rentcast_dump_[zip]_[date]_[time].csv`) alongside a symlinked `rentcast_dump_latest.csv`.
* **FR-5.4:** Ingested listings are transformed and upserted into Supabase `units`.

---

## 5. Non-Functional Requirements (NFRs)

| Attribute | Criteria & Threshold |
| --- | --- |
| **Response Latency** | Time to First Token (TTFT) $< 600\text{ ms}$; full response generation $< 2.0\text{ s}$ using Groq acceleration. |
| **Data Integrity** | Strict ACID transactional semantics in Supabase. Hold creations and status flips execute in unified database transactions. |
| **Availability & Uptime** | 99.9% uptime target for the LangGraph engine and Supabase backend. |
| **Security & Privacy** | Prospect PII (Name, Email, Phone) encrypted at rest in PostgreSQL. Zero external leaks of database connection strings. |
| **Device Responsiveness** | UI renders responsively across desktop resolutions down to $1280\times 720$ utilizing split-screen architecture. |

---

## 6. User Interface & Experience (UI/UX) Specifications

* **Layout Structure:** True 50/50 side-by-side grid (`st.columns([1.1, 1.2], gap="large")`).
* **Left Column (Property Showcase):** Branded hero card, 3 live metrics cards (Available Units, Starting Rent, 48-Hour Approval tag), and high-resolution photo grids of kitchens, amenity decks, and floor plans.
* **Right Column (Concierge Window):** Dedicated conversational console featuring:
* Gradient header with live operational badge (`● Ready`).
* One-click clickable suggestion pills directly above the viewport.
* Fixed-height scroll container (`height=520`) preventing layout shifts during streaming.




* **Visual Theme:** Deep obsidian background (`#0d1527`), frosted glass cards (`rgba(18, 26, 47, 0.85)`), electric cyan accents (`#38bdf8`), and amber concession markers (`#fbbf24`).

---

## 7. Data Models & Database Schema

```sql
-- 1. Units Inventory Table
CREATE TABLE IF NOT EXISTS units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_number VARCHAR(20) UNIQUE NOT NULL,
    building VARCHAR(100) DEFAULT 'The Standard',
    floor INT NOT NULL,
    bedrooms INT NOT NULL,
    bathrooms NUMERIC(3, 1) NOT NULL,
    sqft INT NOT NULL,
    rent_usd NUMERIC(10, 2) NOT NULL,
    status VARCHAR(20) DEFAULT 'vacant' CHECK (status IN ('vacant', 'held', 'reserved', 'leased')),
    vacant_since TIMESTAMPTZ DEFAULT NOW(),
    amenities JSONB DEFAULT '[]'::jsonb,
    photos JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Prospects / Leads Table
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    phone VARCHAR(50),
    preferred_beds INT,
    max_budget_usd NUMERIC(10, 2),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Tour Appointments Table
CREATE TABLE IF NOT EXISTS tours (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id UUID REFERENCES units(id) ON DELETE CASCADE,
    prospect_name VARCHAR(150) NOT NULL,
    prospect_email VARCHAR(150) NOT NULL,
    tour_type VARCHAR(50) DEFAULT 'in_person' CHECK (tour_type IN ('in_person', 'virtual', 'self_guided')),
    scheduled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tours_scheduled_at ON tours(scheduled_at);

-- 4. Temporary VIP Reservation Holds Table
CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id UUID REFERENCES units(id) ON DELETE CASCADE,
    prospect_name VARCHAR(150) NOT NULL,
    prospect_email VARCHAR(150) NOT NULL,
    status VARCHAR(50) DEFAULT 'held' CHECK (status IN ('held', 'paid', 'expired', 'cancelled')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. RAG Policy Knowledge Store
CREATE TABLE IF NOT EXISTS property_knowledge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

```

---

## 8. Success Metrics & Key Performance Indicators (KPIs)

```
       Total Inbound Interactions
                   │
                   ▼
       [Qualified Leads Captured]       ---> Target: ≥ 35% Conversion
                   │
                   ▼
        [Tours Booked / VIP Holds]      ---> Target: ≥ 18% Conversion
                   │
                   ▼
     [Final Leases Signed (Off-Hours)]  ---> Target: ≥ 25% Total Portfolio

```

| Metric | Target Objective | Measurement Method |
| --- | --- | --- |
| **Off-Hours Lead Capture** | $\ge 40\%$ increase in captured prospect contact cards outside 9 AM–5 PM. | Supabase `leads` timestamps vs. business hours. |
| **Tour Scheduling Velocity** | Conversion of chat sessions to booked tours $\ge 18\%$. | Count of rows in `tours` divided by unique chat sessions. |
| **Stale Vacancy Reduction** | Decrease average days-on-market for vacant inventory by $\ge 12\text{ days}$. | Mean delta between `vacant_since` and `tours`/`reservations` creation. |
| **Collision Incidence Rate** | Exactly $0.0\%$ overlapping bookings. | Automated collision audit verifying zero tour intervals $< 45\text{ minutes}$. |
| **Fair Housing Audit Pass Rate** | $100\%$ compliance across red-teaming test suites. | Automated evaluation runs testing responses to prohibited inquiries. |

---

## 9. Risk Analysis & Mitigation Matrix

| Risk Factor | Severity | Probability | Mitigation Strategy |
| --- | --- | --- | --- |
| **LLM Hallucination of Pricing/Availability** | High | Low | Enforce strict structured tool outputs (`search_vacant_units`). Unit data is returned via deterministic SQL queries rather than parametric LLM memory. |
| **Fair Housing Regulatory Violations** | Critical | Low | System prompt hard-boundaries paired with few-shot safety examples. Explicitly forbids demographic, safety, or racial discourse. |
| **Database Lock Contention During Concurrent Holds** | Medium | Medium | Unit reservation operations execute inside strict database transactions using `SELECT FOR UPDATE` on unit records. |
| **Rate Limit Depletion (RentCast API)** | Low | Low | Daily/twice-weekly scheduled cron jobs limit calls to $\sim 10\text{ requests/month}$, well below the 50-request limit. |

---

## 10. Implementation Roadmap & Release Phases

### Phase 1: Core Automation (Current Baseline - Complete)

* Functional LangGraph state workflow with Groq (Qwen 3.8 27B).
* Supabase PostgreSQL relational schema with `pgvector` policy search.
* Dynamic concession calculation for listings vacant $\ge 45$ days.
* 45-minute tour booking collision buffer with Resend transactional email confirmations.
* 15-minute VIP lock tool with embedded animated JavaScript countdown widget.
* Split-screen Streamlit desktop UI with responsive clickable prompt pills.

### Phase 2: Enhanced Omnichannel & Operations (Q4 2026)

* Twilio SMS & WhatsApp webhook proxy connecting the LangGraph state machine to mobile prospects.
* Background cron task executing `expire_stale_holds()` to automatically revert expired holds to `'vacant'`.
* Multi-property expansion: Dynamic `property_id` state injection across multi-building portfolios.

### Phase 3: Autonomous Lease Execution (Q1 2027)

* Multimodal AI pre-screening: Document parsing for automated $3\times$ income-to-rent verification via pay stub/W-2 uploads.
* Smart lock API integration (Latch/Brivo) for generating automated QR code visitor passes upon tour confirmation.
* Dedicated administrative operations dashboard for on-site leasing directors.