"""Small, testable helpers for the interview demo UI."""
import math
import os
from dataclasses import dataclass
from time import monotonic

from langchain_core.messages import AIMessageChunk


def demo_controls_enabled(listener):
    return (os.getenv("DEMO_CONTROLS", "false").lower() == "true"
            and os.getenv("ANALYTICS_MODE", "demo") == "demo"
            and listener in {"127.0.0.1", "::1"})


def consume_request(state, *, now=None, limit=10, window=60):
    """Return seconds to wait, or consume one slot and return zero."""
    now = monotonic() if now is None else now
    recent = [stamp for stamp in state.get("_request_times", []) if now - stamp < window]
    state["_request_times"] = recent
    if len(recent) >= limit:
        return max(1, math.ceil(window - (now - recent[0])))
    recent.append(now)
    return 0


@dataclass
class ReplyStream:
    """Never concatenate different graph steps, retries or model attempts."""
    key: tuple | None = None
    text: str = ""
    has_tool_call: bool = False

    def accept(self, chunk, metadata):
        if not isinstance(chunk, AIMessageChunk) or metadata.get("langgraph_node") != "agent":
            return None
        key = (metadata.get("langgraph_step"), metadata.get("leasing_attempt"), chunk.id)
        if key != self.key:
            self.key, self.text, self.has_tool_call = key, "", False
        if chunk.tool_call_chunks or chunk.tool_calls:
            self.has_tool_call = True
            self.text = ""
        if self.has_tool_call:
            return ""
        content = chunk.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content
                              if isinstance(part, dict) and part.get("type") == "text")
        self.text += content or ""
        return self.text


def reply_caption(message):
    meta = message.response_metadata
    elapsed = meta.get("request_elapsed_seconds")
    if elapsed is None:
        return None
    role = meta.get("served_by")
    if role:
        label = "primary" if role == "primary" else "fallback"
        return f"{elapsed:.1f}s | {label}: {meta.get('served_model', 'unknown')} | checked reply"
    outcome = meta.get("analytics_outcome")
    label = "guardrail" if outcome == "blocked" else "interrupted" if outcome == "interrupted" else "service unavailable" if outcome else "checked reply"
    return f"{elapsed:.1f}s | {label}"


ARCHITECTURE = """flowchart TD
    Request[Guest request] --> Guard[Guardrail]
    Guard -->|Allowed| Agent[Agent: primary / fallback]
    Guard -->|Blocked| Refusal[Refusal]
    Agent -->|Tool call| Tools[Leasing tools]
    Tools --> DB[(PostgreSQL)]
    DB --> Tools
    Tools --> Agent
    Agent -->|Final draft| Evaluator[Grounding evaluator]
    Evaluator --> Reply[Checked reply]
    Tools -. Policy retrieval .-> Embeddings[Local MiniLM + pgvector]
"""
