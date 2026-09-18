"""Browser-session conversations; analytics and request limits stay session-wide."""
from uuid import uuid4

from langchain_core.messages import HumanMessage


def remember_conversation(state):
    state.setdefault("conversation_id", str(uuid4()))
    conversations = state.setdefault("conversations", {})
    messages = state.get("agent_messages", [])
    first = next((m for m in messages if isinstance(m, HumanMessage)), None)
    conversations[state["conversation_id"]] = {
        "title": str(first.content)[:60] if first else "New conversation",
        "messages": list(messages),
        "feedback_request": state.get("feedback_request"),
        "feedback_notice": state.get("feedback_notice"),
    }


def switch_conversation(state, conversation_id=None):
    remember_conversation(state)
    conversation_id = conversation_id or str(uuid4())
    saved = state["conversations"].get(conversation_id, {})
    state["conversation_id"] = conversation_id
    state["agent_messages"] = list(saved.get("messages", []))
    state["feedback_request"] = saved.get("feedback_request")
    state.pop("feedback_notice", None)
    if saved.get("feedback_notice"):
        state["feedback_notice"] = saved["feedback_notice"]

