"""Privacy-limited operational analytics. Never persist prompts or tool payloads."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID, uuid4, uuid5

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

LOGGER = logging.getLogger(__name__)
MODES = ("demo", "live", "test")
SOURCES = ("typed", "suggested", "inventory", "contact")
TOOL_TASKS = {
    "search_vacant_units": "search", "lookup_property_policy": "policy",
    "lookup_market_comps": "market", "list_tour_availability": "availability",
    "book_tour_appointment": "booking", "create_reservation_hold": "hold",
    "capture_prospect_lead": "lead",
}
SUCCESS = ("success", "no_match")
EVENT_COLUMNS = (
    "id", "request_id", "session_id", "kind", "mode", "source", "task",
    "outcome", "suggestion_index", "duration_ms", "resource_id", "rating",
    "error_category", "created_at", "completed_at",
    "model_attempted", "fallback_attempted",
)
SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS analytics_events (
        id uuid PRIMARY KEY, request_id uuid NOT NULL, session_id uuid NOT NULL,
        kind text NOT NULL CHECK (kind IN ('request','tool','feedback')),
        mode text NOT NULL CHECK (mode IN ('demo','live','test')),
        source text NOT NULL CHECK (source IN ('typed','suggested','inventory','contact')),
        task text NOT NULL CHECK (task IN ('search','policy','market','availability',
            'booking','hold','lead','conversation','mixed','unknown')),
        outcome text NOT NULL CHECK (outcome IN ('started','success','no_match',
            'rejected','error','unknown','answered','blocked','partial','unanswered')),
        suggestion_index smallint CHECK (suggestion_index BETWEEN 0 AND 6),
        duration_ms integer CHECK (duration_ms >= 0), resource_id uuid,
        rating smallint CHECK (rating BETWEEN 1 AND 5),
        error_category text CHECK (error_category IN ('exception','interrupted',
            'model_error','model_unavailable','tool_error')),
        created_at timestamptz NOT NULL, completed_at timestamptz,
        CHECK ((source = 'suggested') = (suggestion_index IS NOT NULL)),
        CHECK ((kind = 'feedback') = (rating IS NOT NULL))
    );""",
    "CREATE INDEX IF NOT EXISTS analytics_period_idx ON analytics_events (mode, created_at);",
    "CREATE INDEX IF NOT EXISTS analytics_request_idx ON analytics_events (request_id);",
    # Browser clients must not read anonymous session trails via Supabase's public API.
    "ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;",
    "ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS model_attempted boolean;",
    "ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS fallback_attempted boolean;",
    """ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS analytics_events_suggestion_index_check;
        ALTER TABLE analytics_events ADD CONSTRAINT analytics_events_suggestion_index_check
        CHECK (suggestion_index BETWEEN 0 AND 6);""",
]


def enabled():
    return os.getenv("ANALYTICS_ENABLED", "true").lower() in {"true", "1", "yes"}


def _connect():
    return psycopg2.connect(
        os.environ["SUPABASE_DB_URL"], connect_timeout=2,
        options="-c statement_timeout=2000 -c lock_timeout=1000",
        cursor_factory=RealDictCursor,
    )


def _write(events):
    if not enabled():
        return False
    conn = None
    try:
        conn = _connect()
        with conn:
            with conn.cursor() as cur:
                for event in events:
                    cur.execute(
                        "INSERT INTO analytics_events (" + ",".join(EVENT_COLUMNS) + ") VALUES ("
                        + ",".join(["%s"] * len(EVENT_COLUMNS)) + ") "
                        "ON CONFLICT (id) DO UPDATE SET outcome=EXCLUDED.outcome, "
                        "task=EXCLUDED.task, duration_ms=EXCLUDED.duration_ms, "
                        "resource_id=EXCLUDED.resource_id, rating=EXCLUDED.rating, "
                        "error_category=EXCLUDED.error_category, completed_at=EXCLUDED.completed_at, "
                        "model_attempted=EXCLUDED.model_attempted, fallback_attempted=EXCLUDED.fallback_attempted "
                        "WHERE analytics_events.outcome='started' OR analytics_events.kind='feedback'",
                        tuple(event.get(key) for key in EVENT_COLUMNS),
                    )
        return True
    except Exception:
        # Exceptions can contain credentials, SQL parameters or contact details.
        LOGGER.warning("Analytics write unavailable; leasing operation was not affected.")
        return False
    finally:
        if conn is not None:
            conn.close()


@dataclass
class Request:
    session_id: str
    source: str
    suggestion_index: int | None = None
    task: str = "unknown"
    id: str = field(default_factory=lambda: str(uuid4()))
    mode: str = field(default_factory=lambda: os.getenv("ANALYTICS_MODE", "demo"))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started: float = field(default_factory=perf_counter)

    def event(self, kind="request", **values):
        result = dict.fromkeys(EVENT_COLUMNS)
        result.update(
            id=self.id, request_id=self.id, session_id=self.session_id,
            kind=kind, mode=self.mode, source=self.source, task=self.task,
            outcome="started", suggestion_index=self.suggestion_index,
            created_at=self.created_at,
        )
        result.update(values)
        return result


def begin_request(session_id, source, suggestion_index=None, task="unknown"):
    request = Request(str(UUID(session_id)), source, suggestion_index, task)
    if request.mode not in MODES or source not in SOURCES:
        LOGGER.warning("Analytics disabled for request: invalid mode or source configuration.")
        return None
    if enabled():
        _write([request.event()])
    # Processing latency deliberately excludes event writes and browser rendering.
    request.started = perf_counter()
    return request


def classify_tool(name, content, status="success"):
    """Interpret only known tool contracts; unknown output is never a success."""
    task = TOOL_TASKS.get(name, "unknown")
    text = str(content)
    if status == "error" or text.startswith("Failed to place hold:"):
        return task, "error", None
    if text.startswith("Outcome unknown after interruption"):
        return task, "unknown", None
    if text.startswith("No vacant units found matching those exact filters."):
        return task, "no_match", None
    if text.startswith("No tour slots are open"):
        return task, "no_match", None
    if text.startswith(("No specific written policy matched.", "No nearby market comps are loaded")):
        return task, "unanswered", None
    for tool_name, prefix, resource_key in (
        ("book_tour_appointment", "TOUR_CONFIRMED::", "tour_id"),
        ("create_reservation_hold", "VIP_HOLD_INITIALIZED::", "reservation_id"),
    ):
        if name == tool_name and text.startswith(prefix):
            try:
                payload, _ = json.JSONDecoder().raw_decode(text[len(prefix):])
                return task, "success", str(UUID(payload[resource_key]))
            except (ValueError, KeyError, TypeError):
                return task, "unknown", None
    if name == "capture_prospect_lead" and text.startswith("Lead captured for "):
        return task, "success", None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if name == "search_vacant_units" and isinstance(data, list):
        if not data:
            return task, "no_match", None
        if all(isinstance(row, dict) and {"unit_number", "rent_usd"} <= row.keys() for row in data):
            return task, "success", None
    if name == "lookup_market_comps" and isinstance(data, list) and data:
        if all(isinstance(row, dict) and "avg_rent" in row for row in data):
            return task, "success", None
    if name == "list_tour_availability" and isinstance(data, dict) and isinstance(data.get("slots"), list):
        return task, "success" if data["slots"] else "no_match", None
    if name == "lookup_property_policy" and text.strip():
        return task, "success", None
    if name in TOOL_TASKS and text.strip() and not text.startswith(("{", "[", "TOUR_", "VIP_")):
        return task, "rejected", None
    return task, "unknown", None


def finish_request(request, messages=(), *, tool_result=None, error=None):
    if request is None:
        return False
    duration = max(0, round((perf_counter() - request.started) * 1000))
    completed = datetime.now(timezone.utc)
    # A graph snapshot contains the whole conversation, not just this request.
    boundary = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    current = messages[boundary + 1:]
    results = [(m.tool_call_id, m.name, m.content, m.status) for m in current if isinstance(m, ToolMessage)]
    if tool_result is not None:
        results.append(("form", tool_result[0], tool_result[1], "success"))
    events = {}
    for call_id, name, content, status in results:
        task, outcome, resource_id = classify_tool(name, content, status)
        event_id = str(uuid5(UUID(request.id), str(call_id)))
        events[event_id] = request.event(
            kind="tool", id=event_id, task=task, outcome=outcome,
            resource_id=resource_id, completed_at=completed,
            error_category="tool_error" if outcome == "error" else None,
        )
    flags = [m.response_metadata.get("analytics_outcome") for m in current if isinstance(m, AIMessage)]
    if not error:
        error = next((flag for flag in flags if flag in {"model_error", "model_unavailable"}), None)
    outcomes = [e["outcome"] for e in events.values()]
    if error:
        outcome = "partial" if any(o in SUCCESS for o in outcomes) else "error"
    elif "blocked" in flags:
        outcome = "blocked"
    elif outcomes:
        outcome = "success" if all(o in SUCCESS for o in outcomes) else (
            "partial" if any(o in SUCCESS for o in outcomes) else outcomes[-1]
        )
        if "error" in outcomes:
            error = "tool_error"
    else:
        outcome = "answered" if any(isinstance(m, AIMessage) and m.content and not m.tool_calls for m in current) else "unknown"
    tasks = {e["task"] for e in events.values()}
    task = next(iter(tasks)) if len(tasks) == 1 else "mixed" if tasks else request.task
    if task == "unknown" and outcome == "answered":
        task = "conversation"
    metadata = [m.response_metadata for m in current if isinstance(m, AIMessage)]
    measured = any("model_attempted" in meta for meta in metadata)
    return _write([request.event(
        outcome=outcome, task=task, duration_ms=duration,
        completed_at=completed, error_category=error,
        model_attempted=any(meta.get("model_attempted", False) for meta in metadata) if measured else None,
        fallback_attempted=any(meta.get("fallback_attempted", False) for meta in metadata) if measured else None,
    ), *events.values()])


def save_feedback(request, rating):
    """A revised rating replaces the previous value; clearing it removes that vote."""
    if request is None or not enabled():
        return False
    if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
        raise ValueError("Rating must be an integer from 1 to 5.")
    event_id = str(uuid5(UUID(request.id), "feedback"))
    if rating is not None:
        return _write([request.event(
            kind="feedback", id=event_id, rating=rating, outcome="success",
            completed_at=datetime.now(timezone.utc),
        )])
    conn = None
    try:
        conn = _connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analytics_events WHERE id=%s AND kind='feedback'", (event_id,))
        return True
    except Exception:
        LOGGER.warning("Analytics feedback unavailable.")
        return False
    finally:
        if conn is not None:
            conn.close()


def load_events(mode, start, end, limit=50000):
    if mode not in MODES or not start < end:
        raise ValueError("Choose a valid mode and date range.")
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT " + ",".join(EVENT_COLUMNS) + " FROM analytics_events "
                    "WHERE mode=%s AND created_at >= %s AND created_at < %s "
                    "ORDER BY created_at, id LIMIT %s", (mode, start, end, limit + 1),
                )
                rows = cur.fetchall()
        if len(rows) > limit:
            raise ValueError("More than 50,000 events. Select a shorter date range.")
        return pd.DataFrame(rows, columns=EVENT_COLUMNS)
    finally:
        conn.close()


def load_demo_summary():
    """Return aggregates only; never send session/resource IDs to the sidebar."""
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT
                    count(*) FILTER (WHERE kind='request' AND outcome='blocked') AS blocked,
                    count(*) FILTER (WHERE kind='feedback') AS ratings,
                    avg(rating) FILTER (WHERE kind='feedback') AS mean_rating,
                    count(*) FILTER (WHERE kind='request' AND model_attempted IS TRUE) AS model_requests,
                    count(*) FILTER (WHERE kind='request' AND model_attempted IS TRUE AND fallback_attempted IS TRUE) AS fallback_requests
                    FROM analytics_events WHERE mode='demo' AND created_at >= now() - interval '24 hours'""")
                return dict(cur.fetchone())
    finally:
        conn.close()


def summarize(events):
    """All rates include denominators. Sessions are not deduplicated people."""
    requests = events[events.kind == "request"].copy()
    tools = events[events.kind == "tool"].copy()
    feedback = events[(events.kind == "feedback") & events.request_id.isin(requests.id)]
    tools["completed"] = tools.outcome.isin(SUCCESS)
    search = pd.concat([
        tools[tools.task == "search"], requests[requests.task == "search"],
    ], ignore_index=True)
    bookings = tools[(tools.task == "booking") & (tools.outcome == "success") & tools.resource_id.notna()]
    searching_sessions = set(search.session_id)
    first_search = search.groupby("session_id").created_at.min().to_dict()
    converted = {row.session_id for row in bookings.itertuples()
                 if row.session_id in first_search and row.created_at >= first_search[row.session_id]}
    by_task = tools.groupby(["task", "source"], as_index=False).agg(
        attempts=("id", "count"), completed=("completed", "sum"),
    )
    by_task["completion_percent"] = 100 * by_task.completed / by_task.attempts
    latency = requests[requests.duration_ms.notna()].copy()
    latency["seconds"] = pd.to_numeric(latency.duration_ms) / 1000
    speed = latency.groupby("source", as_index=False).agg(
        samples=("seconds", "count"), p50_seconds=("seconds", "median"),
        p95_seconds=("seconds", lambda s: s.quantile(.95)),
    )
    requests["tool_complete"] = requests.outcome.eq("success")
    suggestions = requests[requests.source == "suggested"].groupby("suggestion_index", as_index=False).agg(
        clicks=("id", "count"), tool_complete=("tool_complete", "sum"),
    )
    suggestions["completion_percent"] = 100 * suggestions.tool_complete / suggestions.clicks
    requests["day"] = pd.to_datetime(requests.created_at, utc=True).dt.date
    daily = requests.groupby(["day", "outcome"]).size().unstack(fill_value=0).reset_index()
    chat = requests[requests.source.isin(["typed", "suggested"])]
    return {
        "requests": len(requests), "sessions": requests.session_id.nunique(),
        "tool_requests": tools.request_id.nunique(), "completed_requests": int(requests.outcome.eq("success").sum()),
        "errors": int(requests.error_category.notna().sum()),
        "unfinished": int(requests.outcome.eq("started").sum()),
        "unverified": int(requests.outcome.isin(["answered", "unknown"]).sum()),
        "search_sessions": len(searching_sessions), "converted_sessions": len(converted),
        "bookings": bookings.resource_id.nunique(), "ratings": len(feedback),
        "mean_rating": None if feedback.empty else float(feedback.rating.mean()),
        "chat_requests": len(chat),
        "median_chat_turns": None if chat.empty else float(chat.groupby("session_id").size().median()),
        "by_task": by_task, "speed": speed, "suggestions": suggestions, "daily": daily,
        "errors_by_category": requests.error_category.dropna().value_counts().rename_axis("category").reset_index(name="requests"),
    }
