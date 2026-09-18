from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from leasing_utils import (
    parse_booking_datetime, has_tour_collision, next_open_tour_slots,
    concession_for_days_vacant, fair_housing_refusal, build_tour_ics,
)

NOW = datetime(2026, 9, 17, 15, tzinfo=timezone.utc)


def test_relative_time_uses_property_timezone():
    assert parse_booking_datetime("tomorrow at 2 PM", NOW) == datetime(2026, 9, 18, 19, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["tomorrow", "tomorrow at 25 PM", "not a date"])
def test_invalid_or_missing_time(value):
    with pytest.raises(ValueError):
        parse_booking_datetime(value, NOW)


def test_collision_boundary():
    assert has_tour_collision(NOW + timedelta(minutes=44, seconds=59), [NOW]) == NOW
    assert has_tour_collision(NOW + timedelta(minutes=45), [NOW]) is None


def test_availability_excludes_booked_slots():
    slots = next_open_tour_slots([], count=3, now=NOW)
    assert next_open_tour_slots([slots[0]], count=1, now=NOW) == [slots[0] + timedelta(minutes=45)]
    assert next_open_tour_slots([], count=0, now=NOW) == []


def test_concession_boundaries():
    assert concession_for_days_vacant(44) is None
    assert "$500" in concession_for_days_vacant(45)
    assert "$750" in concession_for_days_vacant(60)


@pytest.mark.parametrize("text", ["A 2-bedroom for my family", "Is the balcony safe for my cat?"])
def test_ordinary_questions_are_allowed(text):
    assert fair_housing_refusal(text) is None


def test_calendar_escapes_user_input():
    calendar = build_tour_ics("101", "Alex\r\nEND:VEVENT", "a@example.com", NOW, "in_person", "demo")
    assert calendar.count("\r\nEND:VEVENT\r\n") == 1
    assert "DTSTART:20260917T150000Z" in calendar
    assert "DTEND:20260917T154500Z" in calendar


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    import agent3
    return agent3


@pytest.fixture
def db(agent, monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(agent, "get_db_connection", lambda: conn)
    return conn, cursor


def test_search_uses_bound_filters_and_closes_connection(agent, db):
    conn, cursor = db
    cursor.fetchall.return_value = []
    assert "No vacant" in agent.search_vacant_units.invoke({"max_rent": 2000, "bedrooms": 0})
    query, params = cursor.execute.call_args.args
    assert "rent_usd <= %s" in query and "bedrooms = %s" in query
    assert params == (2000, 0, 5, 0)
    conn.close.assert_called_once()


def test_cleanup_preserves_newer_active_hold(agent, db):
    conn, cursor = db
    agent.cleanup_expired_reservations(conn)
    query = cursor.execute.call_args.args[0]
    assert "NOT EXISTS" in query and "active.expires_at > NOW()" in query


def test_hold_rejects_already_held_unit(agent, db):
    conn, cursor = db
    cursor.fetchone.return_value = {"id": "u1", "status": "held"}
    result = agent.create_reservation_hold.invoke({"unit_number": "101", "prospect_name": "Alex", "prospect_email": "a@example.com"})
    assert "cannot be placed on hold" in result
    assert "FOR UPDATE" in cursor.execute.call_args.args[0]
    assert not any("INSERT" in call.args[0] for call in cursor.execute.call_args_list)


def test_lead_upsert_preserves_optional_fields(agent, db):
    conn, cursor = db
    cursor.fetchone.return_value = {"id": "lead1"}
    assert "Lead captured" in agent.upsert_lead("Alex", "a@example.com")
    query, params = cursor.execute.call_args.args
    assert "ON CONFLICT (email)" in query and "COALESCE" in query
    assert params[:2] == ("Alex", "a@example.com")
    conn.commit.assert_called_once()


def test_ui_retains_tool_results_and_requires_consent(agent, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    lead = MagicMock()
    monkeypatch.setattr(agent, "upsert_lead", lead)
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["agent_messages"] = [
        HumanMessage(content="Find a home"),
        AIMessage(content="", tool_calls=[{"name": "search_vacant_units", "args": {}, "id": "search1"}]),
        ToolMessage(content='[{"unit_number":"101","rent_usd":1800,"bedrooms":1,"bathrooms":1,"sqft":700}]', tool_call_id="search1", name="search_vacant_units"),
        AIMessage(content="Unit 101 is available."),
    ]
    app.run()
    assert not app.exception
    assert any(x.value == "Unit 101" for x in app.subheader)
    next(b for b in app.button if b.label == "Request contact").click().run()
    assert not app.exception
    lead.assert_not_called()
    assert len(app.session_state["agent_messages"]) == 4


def test_booking_commits_even_when_email_fails(agent, db, monkeypatch):
    conn, cursor = db
    cursor.fetchone.side_effect = [{"id": "u1", "status": "vacant"}, {"id": "tour1"}]
    cursor.fetchall.return_value = []
    monkeypatch.setattr(agent, "dispatch_tour_confirmation_email", MagicMock(side_effect=RuntimeError("unavailable")))
    result = agent.book_tour_appointment.invoke({"unit_number": "101", "prospect_name": "Alex", "prospect_email": "a@example.com", "date_time": "2030-01-07T14:00:00-06:00"})
    assert "TOUR_CONFIRMED::" in result
    assert "Email unavailable" in result
    assert "Confirmation email dispatched" not in result
    assert any("pg_advisory_xact_lock" in call.args[0] for call in cursor.execute.call_args_list)
    conn.close.assert_called_once()
