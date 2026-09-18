import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from leasing_utils import parse_booking_datetime, validate_tour_time, iter_tour_slot_starts, PROPERTY_TZ
from grounded_replies import grounded_reply

NOW = datetime(2026, 9, 17, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize("text,expected", [
    ("tomorrow at 2 PM UTC", "2026-09-18T14:00:00+00:00"),
    ("tomorrow at 2 PM Pacific", "2026-09-18T21:00:00+00:00"),
    ("tomorrow at 07:30", "2026-09-18T12:30:00+00:00"),
    ("Thursday at 2 PM", "2026-09-17T19:00:00+00:00"),
    ("next Thursday at 2 PM", "2026-09-24T19:00:00+00:00"),
    ("2030-01-07T14:00:00-08:00", "2030-01-07T22:00:00+00:00"),
])
def test_explicit_time_interpretation(text, expected):
    assert parse_booking_datetime(text, NOW).isoformat() == expected


@pytest.mark.parametrize("text", ["tomorrow at 2", "tomorrow at 2 PM Mars", "tomorrow at 2 PM PST", "2026-11-01T01:30:00", "2026-03-08T02:30:00", "2 PM"])
def test_ambiguous_times_require_clarification(text):
    with pytest.raises(ValueError):
        parse_booking_datetime(text, NOW)


def test_last_slot_and_notice_use_same_rule():
    slots = list(iter_tour_slot_starts(NOW, days_ahead=1))
    assert slots[-1].astimezone(PROPERTY_TZ).strftime("%H:%M") == "17:15"
    for slot in slots:
        validate_tour_time(slot, NOW)
    with pytest.raises(ValueError, match="two hours"):
        validate_tour_time(NOW + timedelta(minutes=15), NOW)
    with pytest.raises(ValueError, match="15-minute"):
        validate_tour_time(NOW + timedelta(hours=2, minutes=1), NOW)


def unit_messages(answer):
    return [HumanMessage(content="Show units"), ToolMessage(name="search_vacant_units", tool_call_id="t", content=json.dumps([
        {"unit_number":"601","rent_usd":1250,"bedrooms":0,"bathrooms":1,"sqft":510},
        {"unit_number":"602","rent_usd":1325,"bedrooms":0,"bathrooms":1,"sqft":550},
    ])), AIMessage(content=answer, id="answer")]


def test_swapped_prices_cannot_be_presented():
    result = grounded_reply(unit_messages("Unit 601 costs $1325."))
    assert "Unit 601: $1,250.00" in result
    assert "Unit 602: $1,325.00" in result
    assert "costs $1325" not in result


def test_unverified_claim_without_tools_is_removed():
    text = grounded_reply([HumanMessage(content="Price?"), AIMessage(content="Unit 999 costs $9000.")])
    assert "9000" not in text and "999" not in text


def test_evaluator_replaces_rejected_message():
    import agent3
    messages = unit_messages("Unit 601 costs $9999.")
    merged = add_messages(messages, agent3.post_eval_node({"messages": messages})["messages"])
    answers = [m for m in merged if isinstance(m, AIMessage)]
    assert len(answers) == 1 and answers[0].id == "answer"
    assert "9999" not in answers[0].content


def test_hold_owner_requires_reference_and_email():
    import agent3
    cur = MagicMock()
    unit = {"id": "unit", "status": "held"}
    assert not agent3.can_tour_unit(cur, unit, "guest@example.com")
    cur.execute.assert_not_called()
    cur.fetchone.return_value = None
    assert not agent3.can_tour_unit(cur, unit, "wrong@example.com", "hold")
    cur.fetchone.return_value = {"id": "hold"}
    assert agent3.can_tour_unit(cur, unit, "guest@example.com", "hold")
    assert cur.execute.call_args.args[1] == ("unit", "hold", "guest@example.com")


def test_search_page_and_specials_parameters(monkeypatch):
    import agent3
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    monkeypatch.setattr(agent3, "get_db_connection", lambda: conn)
    agent3.search_vacant_units.invoke({"unit_number":"608", "specials_only":True, "page":2})
    query, params = cur.execute.call_args.args
    assert "INTERVAL '45 days'" in query
    assert "COUNT(*) OVER()" in query
    assert params == ("608",5,5)


def test_curated_inventory_is_complete_and_diverse():
    from seed_demo_inventory import DEMO_UNITS
    assert len(DEMO_UNITS) == len({row[0] for row in DEMO_UNITS}) == 72
    assert all(row[3] > 400 and row[4] > 0 for row in DEMO_UNITS)
    assert len({row[3] for row in DEMO_UNITS}) > 20


def test_empty_ui_filters_are_valid_tool_input(monkeypatch):
    import agent3
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    monkeypatch.setattr(agent3, "get_db_connection", lambda: conn)
    result = agent3.search_vacant_units.invoke({"max_rent":None,"bedrooms":None,"unit_number":None,"specials_only":False,"page":1})
    assert "No vacant" in result


def test_rejected_answer_not_visible_in_ui():
    import agent3
    from streamlit.testing.v1 import AppTest
    messages = unit_messages("Unit 601 costs $9999.")
    merged = add_messages(messages, agent3.post_eval_node({"messages": messages})["messages"])
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["agent_messages"] = merged
    app.run()
    assert not app.exception
    assert not any("9999" in m.value for m in app.markdown)
