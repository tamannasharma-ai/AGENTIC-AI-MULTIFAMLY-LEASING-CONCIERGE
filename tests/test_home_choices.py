from datetime import date, timedelta
from decimal import Decimal
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from streamlit.testing.v1 import AppTest

from home_choices import SUPPORTED_POLICIES, available, estimate_costs, load_choice_records, money


def unit(number="101"):
    return dict(unit_number=number, rent_usd="1800.25", bedrooms=1, bathrooms=1,
                sqft=750, amenities=["Balcony"], status="vacant",
                available_from=date.today(), checked_date=date.today())


def test_known_costs_use_decimal_and_exclude_unknowns():
    result = estimate_costs(unit(), SUPPORTED_POLICIES, applicants=2, pets=2,
                            parking="Garage", vehicles=2, lease_months=6)
    assert result["monthly"] == Decimal("2330.25")
    assert result["first_month_plus_fees"] == Decimal("4330.50")
    assert [r["Charge"] for r in result["rows"] if r["amount"] is None] == [
        "Pet deposit (basis needs confirmation)", "Water, sewer and electricity (usage-based)"]


def test_missing_or_changed_policy_does_not_invent_amounts():
    changed = dict(SUPPORTED_POLICIES, move_in_fees="Security deposit is now $900.")
    result = estimate_costs(unit(), changed)
    assert all(r["amount"] is None for r in result["rows"] if r["Source"] == "move_in_fees")
    missing = estimate_costs(unit(), {})
    assert missing["first_month_plus_fees"] == Decimal("1800.25")


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-5", "not money"])
def test_invalid_money_stays_unknown(value):
    assert money(value) is None


def test_promotions_not_automatically_applied():
    home = dict(unit(), days_vacant=80, special_offer="$750 off and waived admin fee")
    result = estimate_costs(home, SUPPORTED_POLICIES)
    assert next(r["amount"] for r in result["rows"] if r["Charge"] == "Admin fee") == 100
    assert result["monthly"] == Decimal("1860.25")


def test_future_and_held_homes_are_unavailable():
    assert available(unit())
    assert not available(dict(unit(), status="held"))
    assert not available(dict(unit(), available_from=date.today() + timedelta(days=1)))


def test_read_query_binds_numbers_and_rejects_duplicate_policies():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[unit()], [
        {"category": "move_in_fees", "content": SUPPORTED_POLICIES["move_in_fees"]},
        {"category": "move_in_fees", "content": "Different terms"}]]
    homes, policies = load_choice_records(lambda: conn, ["101"])
    assert homes == [unit()]
    assert policies["move_in_fees"] is None
    assert cursor.execute.call_args_list[0].args[1] == (["101"],)
    assert all(c.args[0].startswith("SELECT") for c in cursor.execute.call_args_list)
    conn.close.assert_called_once()


def test_connection_closed_on_read_failure():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        load_choice_records(lambda: conn, ["101"])
    conn.close.assert_called_once()


def test_shortlist_limit_remove_and_estimate(monkeypatch):
    import choice_ui
    loader = MagicMock(return_value=([unit(str(i)) for i in range(1, 4)], dict(SUPPORTED_POLICIES)))
    monkeypatch.setattr(choice_ui, "load_choice_records", loader)
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["inventory"] = [unit(str(i)) for i in range(1, 5)]
    app.run()
    for i in range(3):
        app.button(key=f"save_inventory_{i}_{i+1}").click().run()
    assert not app.exception
    assert len(app.session_state["shortlist"]) == 3
    assert app.button(key="save_inventory_3_4").disabled
    next(b for b in app.button if b.label == "Refresh availability and calculate").click().run()
    assert not app.exception
    loader.assert_called_once()
    assert "choice_records" in app.session_state
    app.button(key="remove_1").click().run()
    assert len(app.session_state["shortlist"]) == 2
    assert "choice_records" not in app.session_state
    assert not app.button(key="save_inventory_3_4").disabled


def test_next_action_enters_chat_once_without_booking(monkeypatch):
    import agent3
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    graph = MagicMock()
    graph.stream.side_effect = lambda state, **kw: iter([("values", {"messages": state["messages"] + [AIMessage(content="Checked.")]})])
    monkeypatch.setattr(agent3, "leasing_app", graph)
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["agent_messages"] = [HumanMessage(content="Find a home"),
        ToolMessage(content=json.dumps([unit()], default=str), tool_call_id="search", name="search_vacant_units"),
        AIMessage(content="Here is a home.")]
    app.run()
    next(b for b in app.button if b.label == "Show tour times").click().run()
    assert not app.exception
    graph.stream.assert_called_once()
    prompt = graph.stream.call_args.args[0]["messages"][-1].content
    assert "Do not book or hold" in prompt
    app.run()
    graph.stream.assert_called_once()
    assert app.session_state["main_tab"] == "Concierge"


def test_failed_refresh_discards_previous_estimate(monkeypatch):
    import choice_ui
    loader = MagicMock(side_effect=[([unit()], dict(SUPPORTED_POLICIES)), RuntimeError("offline")])
    monkeypatch.setattr(choice_ui, "load_choice_records", loader)
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["shortlist"] = {"101": unit()}
    app.run()
    for _ in range(2):
        next(b for b in app.button if b.label == "Refresh availability and calculate").click().run()
    assert not app.exception
    assert "choice_records" not in app.session_state
    assert any("could not be verified" in e.value for e in app.error)
