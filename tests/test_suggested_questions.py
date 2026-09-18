from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("index", range(6))
def test_suggestion_sends_once_and_preserves_history(monkeypatch, index):
    import agent3

    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    graph = MagicMock()
    graph.stream.side_effect = lambda state, **kwargs: iter([
        ("values", {"messages": state["messages"] + [AIMessage(content="Checked the property records.")]})
    ])
    monkeypatch.setattr(agent3, "leasing_app", graph)
    app = AppTest.from_file("../app.py", default_timeout=20)
    app.session_state["agent_messages"] = [HumanMessage(content="Hello"), AIMessage(content="Welcome")]
    app.run()
    question = app.button(key=f"suggestion_{index}").label
    app.button(key=f"suggestion_{index}").click().run()
    assert not app.exception
    graph.stream.assert_called_once()
    messages = app.session_state["agent_messages"]
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == ["Hello", question]
    assert any(m.value == question for m in app.markdown)
    app.run()
    graph.stream.assert_called_once()
    # Deliberately selecting the same suggestion again is a new user request.
    app.button(key=f"suggestion_{index}").click().run()
    assert graph.stream.call_count == 2
    assert not app.exception


def test_typing_still_uses_same_chat_path(monkeypatch):
    import agent3

    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    graph = MagicMock()
    graph.stream.side_effect = lambda state, **kwargs: iter([
        ("values", {"messages": state["messages"] + [AIMessage(content="Checked.")]})
    ])
    monkeypatch.setattr(agent3, "leasing_app", graph)
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.chat_input[0].set_value("Show Unit 608.").run()
    assert not app.exception
    graph.stream.assert_called_once()
    assert graph.stream.call_args.args[0]["messages"][-1].content == "Show Unit 608."


def test_suggestions_disabled_when_chat_unavailable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    assert not app.exception
    assert all(app.button(key=f"suggestion_{i}").disabled for i in range(6))
    assert app.chat_input[0].disabled
