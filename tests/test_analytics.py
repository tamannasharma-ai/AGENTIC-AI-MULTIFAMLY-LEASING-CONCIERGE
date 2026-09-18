import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pandas as pd
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from streamlit.testing.v1 import AppTest

import leasing_analytics as analytics


@pytest.fixture
def recorded(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    rows = {}

    def write(events):
        for event in events:
            previous = rows.get(event["id"])
            if previous is None or previous["outcome"] == "started" or event["kind"] == "feedback":
                rows[event["id"]] = event.copy()
        return True

    monkeypatch.setattr(analytics, "_write", write)
    return rows


def frame(rows):
    return pd.DataFrame(list(rows.values()), columns=analytics.EVENT_COLUMNS)


def tool(name, content, call_id="call", **kwargs):
    return ToolMessage(name=name, content=content, tool_call_id=call_id, **kwargs)


@pytest.mark.parametrize("name,content,status,outcome", [
    ("search_vacant_units", "No vacant units found matching those exact filters.", "success", "no_match"),
    ("search_vacant_units", '[{"unit_number":"101","rent_usd":1900}]', "success", "success"),
    ("search_vacant_units", "[]", "success", "no_match"),
    ("search_vacant_units", "[{broken", "success", "unknown"),
    ("search_vacant_units", "Database error with private data", "error", "error"),
    ("lookup_property_policy", "No specific written policy matched.", "success", "unanswered"),
    ("lookup_property_policy", "Two pets per apartment.", "success", "success"),
    ("lookup_market_comps", "No nearby market comps are loaded yet.", "success", "unanswered"),
    ("lookup_market_comps", '[{"avg_rent":1900}]', "success", "success"),
    ("list_tour_availability", '{"slots":[]}', "success", "no_match"),
    ("book_tour_appointment", "Time Conflict: already booked.", "success", "rejected"),
    ("book_tour_appointment", "TOUR_CONFIRMED::{bad", "success", "unknown"),
    ("create_reservation_hold", "Failed to place hold: private@example.com", "success", "error"),
    ("capture_prospect_lead", "Lead captured for Private (private@example.com) with ID: lead.", "success", "success"),
    ("create_reservation_hold", "Outcome unknown after interruption.", "success", "unknown"),
])
def test_classification(name, content, status, outcome):
    assert analytics.classify_tool(name, content, status)[1] == outcome


def test_only_current_turn_and_no_sensitive_payloads(recorded):
    request = analytics.begin_request(str(uuid4()), "suggested", 0)
    tour_id = str(uuid4())
    messages = [
        HumanMessage(content="Old request"), tool("lookup_property_policy", "Old policy", "old"),
        HumanMessage(content="Private User private@example.com +15555555555"),
        tool("book_tour_appointment", "TOUR_CONFIRMED::" + json.dumps({
            "tour_id": tour_id, "prospect_name": "Private User", "ics": "private@example.com",
        })),
        AIMessage(content="Private tour confirmed."),
    ]
    analytics.finish_request(request, messages)
    analytics.finish_request(request, messages)
    assert len(recorded) == 2
    assert recorded[request.id]["outcome"] == "success"
    assert recorded[request.id]["task"] == "booking"
    assert any(row["resource_id"] == tour_id for row in recorded.values())
    serialized = json.dumps(recorded, default=str)
    assert all(secret not in serialized for secret in ["Private", "private@example.com", "+15555555555", "Old policy"])


@pytest.mark.parametrize("flag,expected", [("model_error", "error"), ("model_unavailable", "error"), ("blocked", "blocked")])
def test_agent_failure_flags_not_success(recorded, flag, expected):
    request = analytics.begin_request(str(uuid4()), "typed")
    analytics.finish_request(request, [AIMessage(content="Please try again.", response_metadata={"analytics_outcome": flag})])
    assert recorded[request.id]["outcome"] == expected


def test_interrupted_booking_keeps_confirmed_resource(recorded):
    request = analytics.begin_request(str(uuid4()), "typed")
    tour_id = str(uuid4())
    analytics.finish_request(request, [tool("book_tour_appointment", f'TOUR_CONFIRMED::{{"tour_id":"{tour_id}"}}')], error="interrupted")
    assert recorded[request.id]["outcome"] == "partial"
    assert analytics.summarize(frame(recorded))["bookings"] == 1


def test_conversation_reply_not_a_verified_task(recorded):
    request = analytics.begin_request(str(uuid4()), "typed")
    analytics.finish_request(request, [AIMessage(content="Which unit?")])
    report = analytics.summarize(frame(recorded))
    assert report["completed_requests"] == 0
    assert report["unverified"] == 1


def test_empty_metrics_no_fabricated_rates():
    report = analytics.summarize(pd.DataFrame(columns=analytics.EVENT_COLUMNS))
    assert report["requests"] == report["sessions"] == report["ratings"] == 0
    assert report["mean_rating"] is None
    assert report["speed"].empty


def test_summary_deduplicates_conversion_and_requires_search_first(recorded):
    now = datetime.now(timezone.utc)
    session = str(uuid4())
    search = analytics.begin_request(session, "inventory", task="search")
    search.created_at = now
    analytics.finish_request(search, tool_result=("search_vacant_units", "No vacant units found matching those exact filters."))
    # Repeated confirmed IDs are one booking; a different session and earlier tours cannot convert this search.
    tour_id = str(uuid4())
    for sid, delta in [(session, 1), (session, 2), (str(uuid4()), 3), (session, -1)]:
        request = analytics.begin_request(sid, "typed")
        request.created_at = now + timedelta(seconds=delta)
        analytics.finish_request(request, [tool("book_tour_appointment", f'TOUR_CONFIRMED::{{"tour_id":"{tour_id}"}}')])
    report = analytics.summarize(frame(recorded))
    assert report["search_sessions"] == report["converted_sessions"] == report["bookings"] == 1
    assert report["requests"] == 5


def test_unfinished_and_failures_remain_in_denominator(recorded):
    session = str(uuid4())
    analytics.begin_request(session, "typed")
    failed = analytics.begin_request(session, "inventory", task="search")
    analytics.finish_request(failed, error="exception")
    request = analytics.begin_request(session, "suggested", 1)
    analytics.finish_request(request, [tool("search_vacant_units", "[]")])
    report = analytics.summarize(frame(recorded))
    assert report["requests"] == 3 and report["completed_requests"] == 1
    assert report["errors"] == 1 and report["unfinished"] == 1
    assert report["search_sessions"] == 1
    assert report["speed"].samples.sum() == 2
    assert report["suggestions"].clicks.sum() == 1


def test_revised_feedback_is_one_rating(recorded):
    request = analytics.begin_request(str(uuid4()), "typed")
    analytics.finish_request(request, [AIMessage(content="Hello")])
    analytics.save_feedback(request, 2)
    analytics.save_feedback(request, 5)
    report = analytics.summarize(frame(recorded))
    assert report["ratings"] == 1 and report["mean_rating"] == 5


def test_analytics_failure_does_not_raise_or_log_secrets(monkeypatch, caplog):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setattr(analytics, "_connect", MagicMock(side_effect=RuntimeError("privatepassword")))
    request = analytics.begin_request(str(uuid4()), "typed")
    assert analytics.finish_request(request, error="exception") is False
    assert "privatepassword" not in caplog.text


def test_disabled_analytics_never_connects(monkeypatch):
    connection = MagicMock(side_effect=AssertionError("Must not connect"))
    monkeypatch.setattr(analytics, "_connect", connection)
    request = analytics.begin_request(str(uuid4()), "typed")
    analytics.finish_request(request, [AIMessage(content="Hello")])
    analytics.save_feedback(request, 1)
    connection.assert_not_called()


def test_write_closes_connection_and_uses_bound_parameters(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    conn = MagicMock()
    monkeypatch.setattr(analytics, "_connect", lambda: conn)
    request = analytics.begin_request(str(uuid4()), "suggested", 0)
    cur = conn.cursor.return_value.__enter__.return_value
    query, params = cur.execute.call_args.args
    assert "ON CONFLICT (id)" in query and "WHERE analytics_events.outcome='started'" in query
    assert request.session_id in params and request.session_id not in query
    conn.close.assert_called_once()


def test_load_filters_mode_and_utc_period(monkeypatch):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setattr(analytics, "_connect", lambda: conn)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    assert analytics.load_events("demo", start, end).empty
    query, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert "mode=%s" in query and "created_at < %s" in query
    assert params == ("demo", start, end, 50001)
    conn.close.assert_called_once()


def test_chat_click_feedback_and_rerun_do_not_inflate_metrics(recorded, monkeypatch):
    import agent3

    graph = MagicMock()
    graph.stream.side_effect = lambda state, **kwargs: iter([("values", {"messages": state["messages"] + [
        tool("search_vacant_units", "[]"), AIMessage(content="No matching units."),
    ]})])
    monkeypatch.setattr(agent3, "leasing_app", graph)
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.button(key="suggestion_0").click().run()
    assert not app.exception
    app.feedback[0].set_value(0).run()
    assert not app.exception
    app.feedback[0].set_value(4).run()
    app.run()
    report = analytics.summarize(frame(recorded))
    assert report["requests"] == report["ratings"] == 1
    assert report["mean_rating"] == 5
    graph.stream.assert_called_once()
    assert all(row["mode"] == "test" for row in recorded.values())


def test_form_search_is_tracked_without_contact_details(recorded, monkeypatch):
    import agent3

    monkeypatch.setattr(agent3, "search_vacant_units", MagicMock(invoke=MagicMock(return_value="[]")))
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    next(button for button in app.button if button.label == "Search homes").click().run()
    assert not app.exception
    report = analytics.summarize(frame(recorded))
    assert report["requests"] == report["completed_requests"] == 1
    assert set(frame(recorded).source) == {"inventory"}


def test_dashboard_fails_closed_without_local_listener(monkeypatch):
    import streamlit as st

    original = st.get_option
    monkeypatch.setattr(st, "get_option", lambda key: "0.0.0.0" if key == "server.address" else original(key))
    monkeypatch.setattr(analytics, "load_events", MagicMock(side_effect=AssertionError("Must not query")))
    app = AppTest.from_file("../metrics_app.py", default_timeout=20).run()
    assert not app.exception
    assert any("local-only" in item.value for item in app.error)


@pytest.mark.parametrize("populated", [False, True])
def test_dashboard_local_empty_and_populated(recorded, monkeypatch, populated):
    import streamlit as st

    if populated:
        request = analytics.begin_request(str(uuid4()), "suggested", 0)
        analytics.finish_request(request, [tool("search_vacant_units", "[]")])
    monkeypatch.setattr(analytics, "load_events", lambda *args, **kwargs: frame(recorded))
    original = st.get_option
    monkeypatch.setattr(st, "get_option", lambda key: "127.0.0.1" if key == "server.address" else original(key))
    st.cache_data.clear()
    app = AppTest.from_file("../metrics_app.py", default_timeout=20).run()
    assert not app.exception
    if populated:
        assert next(m for m in app.metric if m.label == "Requests").value == "1"
        assert any(m.value == "N/A" for m in app.metric)
    else:
        assert any("No recorded activity" in item.value for item in app.info)
