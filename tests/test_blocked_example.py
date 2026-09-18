from unittest.mock import MagicMock

import streamlit as st
from langchain_core.messages import HumanMessage
from streamlit.testing.v1 import AppTest

import leasing_analytics as analytics
from chat_suggestions import BLOCKED_EXAMPLE_INDEX, SUGGESTED_QUESTIONS


def test_example_uses_real_guardrail_and_refreshes_metric_once(monkeypatch):
    import agent3

    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("ANALYTICS_MODE", "demo")
    monkeypatch.setenv("DEMO_CONTROLS", "true")
    original = st.get_option
    monkeypatch.setattr(st, "get_option", lambda key: "127.0.0.1" if key == "server.address" else original(key))
    guard = MagicMock()
    model = MagicMock()
    monkeypatch.setattr(agent3, "groq_client", guard)
    monkeypatch.setattr(agent3, "llm_chain", [("primary", "test", model)])
    rows = {}

    def write(events):
        for event in events:
            rows[event["id"]] = event.copy()
        return True

    def summary():
        return {"blocked": sum(row["kind"] == "request" and row["outcome"] == "blocked" for row in rows.values()),
                "mean_rating": None, "ratings": 0, "model_requests": 0, "fallback_requests": 0}

    monkeypatch.setattr(analytics, "_write", write)
    monkeypatch.setattr(analytics, "load_demo_summary", summary)
    st.cache_data.clear()
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    assert next(m for m in app.metric if m.label == "Blocked prompts").value == "0"
    app.button(key="blocked_prompt_example").click().run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == "Blocked prompts").value == "1"
    assert [m.content for m in app.session_state["agent_messages"] if isinstance(m, HumanMessage)] == [SUGGESTED_QUESTIONS[BLOCKED_EXAMPLE_INDEX][0]]
    request = next(row for row in rows.values() if row["kind"] == "request")
    assert request["outcome"] == "blocked" and request["suggestion_index"] == BLOCKED_EXAMPLE_INDEX
    guard.chat.completions.create.assert_not_called()
    model.stream.assert_not_called()
    app.run()
    assert next(m for m in app.metric if m.label == "Blocked prompts").value == "1"
    st.cache_data.clear()


def test_example_not_exposed_without_demo_controls():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    assert not app.exception
    assert not any(button.key == "blocked_prompt_example" for button in app.button)
