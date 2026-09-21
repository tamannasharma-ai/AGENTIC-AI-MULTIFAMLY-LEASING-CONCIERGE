# Product Requirements Document: Multifamily Leasing Concierge
**Document Version:** 1.0  
**Status:** Approved for Implementation & Staging  
**Author:** Tamanna  
**Role:** AI Engineer & Data Scientist  
**Date:** September 2026  

---

## Live Interactive Prototype

Test the live prototype directly within the interactive container below:

<div style="position: relative; width: 100%; height: 750px; border: 1px solid #e1e4e8; border-radius: 8px; overflow: hidden; margin-bottom: 2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
  <iframe 
    src="https://your-streamlit-app-url.streamlit.app/?embed=true" 
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;"
    allow="camera; microphone; clipboard-read; clipboard-write;"
    title="Multifamily Leasing Concierge Live Demo">
  </iframe>
</div>

> *Tip: Replace `https://your-streamlit-app-url.streamlit.app/?embed=true` with your production deployment URL.*

---

## 01 · Executive Summary

The **Multifamily Leasing Concierge** is an autonomous, agentic leasing assistant designed for direct deployment across multifamily residential communities. The system enables prospective renters to query real-time vacancy data, verify property rules and policies against canonical documents, schedule guided tours, place 15-minute temporary holds on specific units, build shortlists, and calculate first-month move-in costs in a single conversational thread.

To eliminate legal liabilities and customer friction, the system enforces a strict separation between generation and execution:
1. **Deterministic Guardrails:** Every user turn passes through a compliance and safety screen prior to agent evaluation.
2. **Read/Write Decoupling:** The language model never writes directly to persistent storage; all state changes execute through audited deterministic tools backed by row-level database locks.
3. **Automated Evidence Evaluation:** Factual statements concerning pricing, terms, and availability are audited by an independent evaluator node against tool outputs prior to rendering.

---

## 02 · Problem Statement & Market Context

Apartment leasing decisions are high-velocity and sensitive to latency. Prospective renters routinely evaluate multiple properties simultaneously; delays in verifying basic pet policies, parking surcharges, or current concessions frequently lead to drop-off. Conversely, leasing offices operate on single-threaded, human-dependent business hours where repetitive informational inquiries consume high-value staff time.

A production multifamily leasing agent cannot operate as an open-ended conversational bot:
* **Regulatory Compliance:** Real estate leasing interfaces are legally bound by Fair Housing mandates prohibiting disparate treatment or discriminatory disclosures (e.g., demographic composition, subjective neighborhood safety assessments).
* **Inventory Consistency:** Concurrent prospective renters evaluating the same unit cannot be permitted to double-book appointments or place overlapping holds.
* **Factual Integrity:** Hallucinated concessions, misstated fee structures, or invented policies expose the operating property to financial loss and binding disputes.

The architecture specified herein solves these constraints via stateful workflow orchestration and verified database transactions.

---

## 03 · Personas & User Journeys

| Persona | Core Need | Required System Capabilities |
| :--- | :--- | :--- |
| **Self-Serve Prospect** | Rapid, after-hours evaluation and booking. | Real-time availability search, policy Q&A, instant 15-minute VIP unit reservation, and tour booking. |
| **Comparison Shopper** | Full cost transparency across shortlist units. | Persistent session shortlist, transparent breakdown of one-time deposits vs. recurring fees, and alternative unit recommendations on search miss. |
| **Operations / Leasing Lead** | Funnel visibility and reliability telemetry without privacy exposure. | Real-time conversion tracking, tool execution failure analytics, latency distributions, and localized demo controls. |

---

## 04 · System Architecture

The orchestration engine uses a state machine graph composed of four discrete execution nodes to ensure zero unchecked output reaches the client.
[ Prospective Renter ]
│
▼
┌─────────────────────────────────────────┐
│ 1. Guardrail Node                       │
│ - Fair Housing Compliance Screen        │
│ - Prompt Injection Classifier           │
└──────────────────┬──────────────────────┘
│ Pass
▼
┌─────────────────────────────────────────┐
│ 2. Agent Orchestrator                   │
│ - Intent Classification                 │
│ - Tool Execution Decision               │
│ - Primary & Fallback LLM Dispatch       │
└──────────┬──────────────────────────────┘
│
├──────────────────────────────┐
▼                              ▼
┌───────────────────────┐      ┌─────────────────────────┐
│ 3. Deterministic Tools│      │ Synthesis Layer         │
│ - Live Vacancy Search │      │ Candidate response      │
│ - Policy Vector RAG   │      │ generated               │
│ - DB Concurrency Locks│      └──────────┬──────────────┘
│ - Calendar Dispatch   │                 │
└──────────┬────────────┘                 │
│ Tool Observations            │
└──────────────────────────────┤
▼
┌─────────────────────────────────────────┐
│ 4. Groundedness Evaluator Node          │
│ - Compares response to tool facts       │
│ - Replaces drifted text if ungrounded   │
└──────────────────┬──────────────────────┘
│ Verified Response
▼
[ Prospective Renter ]

### Architectural Guardrails

* **Independent Pre-Execution Screen:** User input is scanned for adversarial injection and Fair Housing inquiries prior to triggering model inference. Non-compliant inquiries receive a deterministic system response.
* **Deterministic Tool Invocation:** The model emits parameterized function calls to validated tools (`search_vacant_units`, `lookup_property_policy`, `book_tour_appointment`). Each tool independently sanitizes input parameters and enforces schema constraints.
* **Observable Model Fallback:** Inference includes primary model routing with automatic transition to a secondary open-weight model on latency thresholds or tool schema parse errors.
* **Pre-Delivery Verification:** Candidate generation text is scored by an evaluation step against the JSON payloads returned by active tools. If a price or policy claim lacks tool corroboration, the system substitutes a sanitized, tool-grounded template.

---

## 05 · Functional Requirements
FR-01: Inventory Search

Support parametric filtering: rent min/max, bedroom count, specific amenities.

Automatically append eligible concessions for units vacant >= 45 days.

Return alternative units differing by exactly one parameter when searches yield 0 results.

FR-02: Grounded Policy Retrieval

Retrieve pet limits, parking assignments, and lease rules via dense vector retrieval.

Generate zero out-of-context policy statements; fall back to leasing office contact info on miss.

FR-03: Transactional Tour Booking

Parse natural-language relative timestamps ("tomorrow at 3 PM").

Enforce 45-minute booking slots, two hours minimum lead time, and operating business hours.

Prevent race conditions via database-level transaction locks.

FR-04: Concurrency-Controlled Holds

Grant temporary 15-minute exclusive holds to a verified prospect identifier.

Lock the corresponding unit inventory record, releasing automatically on TTL expiration.

FR-05: Move-in Cost Formulation

Generate itemized billing schedules separating base rent, recurring utilities/amenities,
and refundable security deposits.


---

## 06 · Non-Functional Requirements

* **Transaction Isolation:** All hold allocations and appointment bookings must execute within serializable database transactions using PostgreSQL row-level locks (`SELECT FOR UPDATE`) to prevent double-allocation.
* **Data Privacy:** Analytical metrics capture session tokens, tool names, execution duration, and outcome status codes only. Unhashed prospect names, contact numbers, email addresses, and raw chat prompts must not be written to analytical storage.
* **Performance SLAs:** 
  * Median response latency (first token rendered): `< 1.2s`
  * Complex multi-tool turns (p95): `< 3.5s`
* **Defensive Failure Mode:** If an integration service (e.g., calendar sync, transactional email) returns an error, the database transaction remains intact and the user is provided a valid booking confirmation code directly in the interface.

---

## 07 · Verification & Evaluation Metrics

| Metric | Target Specification | Measurement Mechanism |
| :--- | :--- | :--- |
| **Tool Execution Completion** | $\ge 95\%$ | Track successful JSON output returns across all tool calls. |
| **Factual Accuracy** | $100\%$ | Automated evaluation of tool payload vs. model claim. |
| **Concurrency Collisions** | $0$ Double Allocations | Load-tested concurrent write attempts on identical units. |
| **Fallback Rate** | $< 5\%$ of total turns | Ratio of requests requiring secondary model invocation. |
| **Search-to-Tour Funnel** | Tracked | Distinct sessions initiating search that complete booking. |

---

## 08 · System Roadmap

### Phase 1: Core Engine Staging *(Current)*
* End-to-end multi-node state graph operational.
* Verification of 7 core deterministic tools.
* Localized Streamlit user testing environment with embedded metrics telemetry.

### Phase 2: Enterprise Integration
* Integration with property management database schemas.
* Multi-channel ingestion (SMS, Email, Webhooks).
* Persistent conversation state storage across multi-device user journeys.

### Phase 3: Advanced Operations
* Multi-community routing across portfolio listings.
* Direct staff escalation triggers for edge cases and exceptions.
* Multi-lingual Fair Housing policy compliance validation.