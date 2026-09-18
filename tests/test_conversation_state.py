from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from streamlit.testing.v1 import AppTest

from conversation_state import remember_conversation, switch_conversation


def test_switch_retains_tools_feedback_and_session_limits():
    messages = [HumanMessage(content="Find a home"),
                AIMessage(content="", tool_calls=[{"id": "search", "name": "search_vacant_units", "args": {}}]),
                ToolMessage(content="[]", tool_call_id="search", name="search_vacant_units")]
    state = {"agent_messages": messages, "feedback_request": "request-1",
             "feedback_notice": "Rating saved.", "analytics_session_id": "session-1",
             "_request_times": [123]}
    remember_conversation(state)
    original = state["conversation_id"]
    switch_conversation(state)
    assert state["agent_messages"] == []
    assert state["feedback_request"] is None
    assert "feedback_notice" not in state
    state["agent_messages"] = [HumanMessage(content="Another search")]
    switch_conversation(state, original)
    assert state["agent_messages"] == messages
    assert state["feedback_request"] == "request-1"
    assert state["feedback_notice"] == "Rating saved."
    assert state["analytics_session_id"] == "session-1"
    assert state["_request_times"] == [123]


def test_new_chat_and_restore_in_ui():
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["agent_messages"] = [HumanMessage(content="Original question"), AIMessage(content="Original answer")]
    app.run()
    original = app.session_state["conversation_id"]
    session = app.session_state["analytics_session_id"]
    next(b for b in app.button if b.label == "New chat").click().run()
    assert not app.exception
    assert app.session_state["agent_messages"] == []
    app.button(key=f"conversation_{original}").click().run()
    assert not app.exception
    assert app.session_state["agent_messages"][-1].content == "Original answer"
    assert app.session_state["analytics_session_id"] == session
    next(b for b in app.button if b.label == "Clear conversation").click().run()
    assert app.session_state["agent_messages"] == []
    assert app.session_state["conversations"][original]["messages"] == []
