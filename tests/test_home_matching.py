import json
from copy import deepcopy
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from home_matching import find_alternatives, match_reasons


def test_explanations_distinguish_missing_preferences():
    reasons = match_reasons({"rent_usd": "1500", "bedrooms": 1, "amenities": '["dishwasher"]'},
                            {"max_rent": 1600, "bedrooms": 1, "required_amenities": ["dishwasher"], "preferred_amenities": ["balcony"]})
    assert "$100.00 below your rent limit" in reasons
    assert "Must-have: Dishwasher" in reasons
    assert "Preference not recorded: Balcony" in reasons


def test_alternatives_change_one_constraint_without_mutation():
    filters = dict(max_rent=1400, bedrooms=1, unit_number=None, specials_only=True,
                   page=1, required_amenities=["balcony", "dishwasher"], preferred_amenities=["patio"])
    original = deepcopy(filters)
    search = MagicMock(side_effect=[json.dumps([{"unit_number": "201", "rent_usd": "1500"}]),
                                   json.dumps([{"unit_number": "202", "rent_usd": "1350"}]),
                                   "No vacant units found matching those exact filters."])
    proposals = find_alternatives(search, filters)
    assert filters == original
    assert len(proposals) == 2
    assert proposals[0]["filters"]["max_rent"] == 1500
    assert proposals[0]["filters"]["required_amenities"] == ["balcony", "dishwasher"]
    assert proposals[1]["filters"]["max_rent"] == 1400
    assert proposals[1]["filters"]["required_amenities"] == ["dishwasher"]
    for call in search.call_args_list:
        assert call.args[0]["bedrooms"] == 1
        assert call.args[0]["specials_only"] is True
        assert call.args[0]["preferred_amenities"] == []


def test_unlimited_budget_without_must_haves_has_no_probes():
    search = MagicMock()
    assert find_alternatives(search, {"max_rent": None}) == []
    search.assert_not_called()


def test_must_haves_filter_before_pagination_and_preferences_sort(monkeypatch):
    import agent3
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    monkeypatch.setattr(agent3, "get_db_connection", lambda: conn)
    agent3.search_vacant_units.invoke(dict(max_rent=2000, required_amenities=["balcony"], preferred_amenities=["patio"], page=2))
    sql, params = cur.execute.call_args.args
    assert sql.index("?&") < sql.index("ORDER BY") < sql.index("LIMIT")
    assert "unnest" in sql
    assert params == (2000, ["balcony"], ["patio"], 5, 5)
    conn.close.assert_called_once()


def test_unsupported_feature_never_queries_database(monkeypatch):
    import agent3
    connect = MagicMock()
    monkeypatch.setattr(agent3, "get_db_connection", connect)
    result = agent3.search_vacant_units.invoke({"required_amenities": ["demographic profile"]})
    assert "supported" in result
    connect.assert_not_called()


def test_ui_requires_acceptance_and_updates_visible_filters(monkeypatch):
    import agent3
    home = dict(unit_number="201", rent_usd=1600, bedrooms=1, bathrooms=1, sqft=750, amenities=[])
    search = MagicMock(side_effect=["No vacant units found matching those exact filters.",
                                   json.dumps([home]), json.dumps([home])])
    monkeypatch.setattr(agent3, "search_vacant_units", MagicMock(invoke=search))
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.number_input(key="search_budget").set_value(1500)
    next(b for b in app.button if b.label == "Search homes").click().run()
    next(b for b in app.button if b.label == "Check one-change alternatives").click().run()
    assert not app.exception
    assert app.session_state["inventory"] == []
    assert app.session_state["inventory_filters"]["max_rent"] == 1500
    app.button(key="alternative_0").click().run()
    assert not app.exception
    assert search.call_count == 3
    assert app.session_state["inventory_filters"]["max_rent"] == 1600
    assert app.number_input(key="search_budget").value == 1600
    assert len(app.session_state["inventory"]) == 1
    app.run()
    assert search.call_count == 3


def test_page_overflow_does_not_offer_relaxation(monkeypatch):
    import agent3
    monkeypatch.setattr(agent3, "search_vacant_units", MagicMock(invoke=MagicMock(return_value="No vacant units found matching those exact filters.")))
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.number_input(key="search_page").set_value(9)
    next(b for b in app.button if b.label == "Search homes").click().run()
    assert not app.exception
    assert not any(b.label == "Check one-change alternatives" for b in app.button)
