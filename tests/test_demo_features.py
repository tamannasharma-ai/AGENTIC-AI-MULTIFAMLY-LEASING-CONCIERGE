from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from streamlit.testing.v1 import AppTest

from demo_features import ReplyStream, consume_request, demo_controls_enabled, reply_caption


def test_rate_limit_boundary_and_no_unbounded_rejected_attempts():
    state = {}
    for _ in range(10):
        assert consume_request(state, now=100) == 0
    assert consume_request(state, now=159) == 1
    assert len(state["_request_times"]) == 10
    assert consume_request(state, now=160) == 0
    assert len(state["_request_times"]) == 1


@pytest.mark.parametrize("enabled,mode,listener,allowed", [
    ("true", "demo", "127.0.0.1", True),
    ("true", "live", "127.0.0.1", False),
    ("false", "demo", "127.0.0.1", False),
    ("true", "demo", "0.0.0.0", False),
    ("true", "demo", None, False),
])
def test_demo_controls_fail_closed(monkeypatch, enabled, mode, listener, allowed):
    monkeypatch.setenv("DEMO_CONTROLS", enabled)
    monkeypatch.setenv("ANALYTICS_MODE", mode)
    assert demo_controls_enabled(listener) is allowed


def test_token_stream_resets_across_fallback_and_steps():
    stream = ReplyStream()
    meta = {"langgraph_node": "agent", "langgraph_step": 1, "leasing_attempt": "primary"}
    assert stream.accept(AIMessageChunk(id="a", content="Hello"), meta) == "Hello"
    assert stream.accept(AIMessageChunk(id="a", content=" there"), meta) == "Hello there"
    assert stream.accept(AIMessageChunk(id="b", content="Fallback"), {**meta, "leasing_attempt": "fallback_1"}) == "Fallback"
    assert stream.accept(AIMessageChunk(id="b", content="Next"), {**meta, "langgraph_step": 3}) == "Next"
    assert stream.accept(AIMessageChunk(content="Internal"), {"langgraph_node": "guardrail"}) is None


def test_tool_arguments_and_reasoning_are_not_streamed_as_reply():
    stream = ReplyStream()
    meta = {"langgraph_node": "agent"}
    assert stream.accept(AIMessageChunk(id="a", content=[{"type": "reasoning", "text": "secret"}, {"type": "text", "text": "Hello"}]), meta) == "Hello"
    assert stream.accept(AIMessageChunk(id="a", content="", tool_call_chunks=[{"name": "search_vacant_units", "args": "{}", "id": "call", "index": 0}]), meta) == ""
    assert stream.accept(AIMessageChunk(id="a", content="Tool preamble"), meta) == ""


def test_real_graph_emits_tokens_and_evaluated_snapshot(monkeypatch):
    import agent3
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    monkeypatch.setattr(agent3, "validate_user_input", lambda _: (True, ""))
    monkeypatch.setattr(agent3, "llm_chain", [("primary", "fake-primary", FakeListChatModel(responses=["Hello"]))])
    events = list(agent3.leasing_app.stream({"messages": [HumanMessage(content="Hi")]}, stream_mode=["values", "messages"]))
    stream = ReplyStream()
    texts = [stream.accept(*payload) for kind, payload in events if kind == "messages"]
    assert "H" in texts and "Hello" in texts
    final = [payload for kind, payload in events if kind == "values"][-1]["messages"][-1]
    assert final.content == "Hello"
    assert final.response_metadata["served_model"] == "fake-primary"
    assert final.response_metadata["model_attempted"] is True


def test_fallback_metadata_includes_failed_primary_time(monkeypatch):
    import agent3

    primary, fallback = MagicMock(), MagicMock()
    primary.stream.side_effect = RuntimeError("private error")
    fallback.stream.return_value = iter([AIMessageChunk(id="fallback", content="Hello")])
    monkeypatch.setattr(agent3, "llm_chain", [("primary", "first", primary), ("fallback_1", "second", fallback)])
    timer = iter([10.0, 13.5])
    monkeypatch.setattr(agent3.time, "perf_counter", lambda: next(timer))
    result = agent3.agent_node({"messages": [HumanMessage(content="Hi")]})["messages"][0]
    assert result.response_metadata["elapsed_seconds"] == 3.5
    assert result.response_metadata["fallback_attempted"] is True
    assert result.response_metadata["served_model"] == "second"
    assert result.id == "fallback"


def test_reset_is_denied_before_database_access(monkeypatch):
    import agent3

    database = MagicMock()
    monkeypatch.setattr(agent3, "get_db_connection", database)
    with pytest.raises(PermissionError):
        agent3.reset_demo_data()
    database.assert_not_called()


def test_reset_only_uses_expiry_cleanup(monkeypatch):
    import agent3

    monkeypatch.setattr(agent3, "demo_controls_enabled", lambda _: True)
    conn = MagicMock()
    monkeypatch.setattr(agent3, "get_db_connection", lambda: conn)
    result = agent3.reset_demo_data()
    calls = conn.cursor.return_value.__enter__.return_value.execute.call_args_list
    assert len(calls) == 2
    assert "expires_at <= NOW()" in calls[0].args[0]
    assert "NOT EXISTS" in calls[1].args[0] and "active.status = 'confirmed'" in calls[1].args[0]
    assert "preserved" in result
    conn.close.assert_called_once()


@pytest.mark.parametrize("name,args", [("lookup_property_policy", {"query": "Pet rules?"}), ("lookup_market_comps", {"bedrooms": 1})])
def test_read_tools_cache_and_can_be_cleared(monkeypatch, name, args):
    import agent3

    cached_tool = getattr(agent3, name)
    cached_tool.func.clear()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(agent3, "get_db_connection", connect)
    monkeypatch.setattr(agent3, "get_embed_model", MagicMock())
    try:
        assert cached_tool.invoke(args) == cached_tool.invoke(args)
        assert connect.call_count == 1
        cached_tool.func.clear()
        cached_tool.invoke(args)
        assert connect.call_count == 2
    finally:
        cached_tool.func.clear()


def test_ui_replaces_streamed_draft_before_final_display(monkeypatch):
    import agent3

    graph = MagicMock()
    def events(state, **kwargs):
        assert kwargs["stream_mode"] == ["values", "messages"]
        yield "messages", (AIMessageChunk(id="draft", content="Unit 101 is $1."), {"langgraph_node": "agent"})
        yield "values", {"messages": state["messages"] + [AIMessage(id="draft", content="Checked price: $1,900.", response_metadata={"served_by": "primary", "served_model": "test-model"})]}
    graph.stream.side_effect = events
    monkeypatch.setattr(agent3, "leasing_app", graph)
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.chat_input[0].set_value("Price?").run()
    assert not app.exception
    assert any(m.value == "Checked price: $1,900." for m in app.markdown)
    assert not any(m.value == "Unit 101 is $1." for m in app.markdown)
    assert any("primary: test-model" in m.value for m in app.caption)
    assert not any(b.label == "Reset demo" for b in app.button)


def test_rate_limited_ui_does_not_call_agent(monkeypatch):
    import agent3
    from time import monotonic

    graph = MagicMock()
    monkeypatch.setattr(agent3, "leasing_app", graph)
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.session_state["_request_times"] = [monotonic()] * 10
    app.chat_input[0].set_value("Hi").run()
    assert not app.exception
    graph.stream.assert_not_called()
    assert any("Too many requests" in w.value for w in app.warning)


def test_fallback_attempt_is_recorded_without_email(monkeypatch):
    import leasing_analytics as analytics

    rows = []
    monkeypatch.setattr(analytics, "_write", lambda events: rows.extend(events) or True)
    request = analytics.begin_request(str(uuid4()), "typed")
    analytics.finish_request(request, [HumanMessage(content="private@example.com"), AIMessage(content="Hello", response_metadata={"model_attempted": True, "fallback_attempted": True})])
    assert rows[-1]["model_attempted"] is True and rows[-1]["fallback_attempted"] is True
    assert "private@example.com" not in str(rows)


def test_caption_does_not_attribute_guardrail_to_model():
    message = AIMessage(content="No", response_metadata={"analytics_outcome": "blocked", "request_elapsed_seconds": 1.2})
    assert reply_caption(message) == "1.2s | guardrail"
