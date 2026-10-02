"""
Call tracing: records every LLM call made through model_prompting as one JSON line.

Enable by setting MARBLE_TRACE=<path to a .jsonl file>; calls are appended to it.
The caller (agent / planner / judge) and step (method name) are read from the call
stack, so agents and planners need no changes. View a trace with scripts/trace_view.py.
"""

import inspect
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

TRACE_PATH = os.environ.get("MARBLE_TRACE")
_ROLE_NAMES = {"EnginePlanner": "planner", "Evaluator": "judge", "Engine": "engine"}
_lock = threading.Lock()
_seq = 0


def _label(obj: Any) -> str:
    agent_id = getattr(obj, "agent_id", None)
    if isinstance(agent_id, str):
        return agent_id
    name = type(obj).__name__
    return _ROLE_NAMES.get(name, name)


def _inspect_stack(tool_names: List[str]) -> Dict[str, Any]:
    """
    Walk the call stack (outermost first) and collect the marble methods on it.
    """
    frames: List[str] = []
    iteration: Optional[int] = None
    speaker: Optional[str] = None
    frame = inspect.currentframe()
    stack = []
    while frame is not None:
        stack.append(frame)
        frame = frame.f_back
    for f in reversed(stack):
        if not f.f_globals.get("__name__", "").startswith("marble."):
            continue
        obj = f.f_locals.get("self")
        if obj is None:
            continue
        frames.append(f"{_label(obj)}.{f.f_code.co_name}")
        if type(obj).__name__ == "Engine":
            iteration = getattr(obj, "current_iteration", None)
        # In a communication session the caller's method runs turns for both agents
        current = f.f_locals.get("session_current_agent")
        if current is not None:
            speaker = _label(current)
    caller, _, step = frames[-1].partition(".") if frames else ("unknown", "", "")
    if step == "_handle_new_communication_session":
        # Turns offer the communicate_to tool; the closing summary is the initiator's own call
        if speaker is not None and "communicate_to" in tool_names:
            caller, step = speaker, "communication_turn"
        else:
            step = "communication_summary"
    return {
        "caller": caller,
        "step": step,
        "stack": frames,
        "iteration": iteration,
    }


def record_call(
    llm_model: str,
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]],
    completion: Any,
    latency: float,
) -> None:
    """
    Append one LLM call to the trace file. No-op unless MARBLE_TRACE is set.
    """
    global _seq
    if not TRACE_PATH:
        return
    message = completion.choices[0].message
    tool_calls = [
        {"name": tc.function.name, "arguments": tc.function.arguments}
        for tc in (message.tool_calls or [])
    ]
    tool_names = [t.get("function", {}).get("name") for t in tools or []]
    usage = getattr(completion, "usage", None)
    event = {
        **_inspect_stack(tool_names),
        "model": llm_model,
        "time": time.time(),
        "latency": round(latency, 3),
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "messages": messages,
        "tools": tool_names,
        "response": message.content,
        "tool_calls": tool_calls,
    }
    with _lock:
        _seq += 1
        event = {"seq": _seq, "pid": os.getpid(), **event}
        os.makedirs(os.path.dirname(TRACE_PATH) or ".", exist_ok=True)
        with open(TRACE_PATH, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
