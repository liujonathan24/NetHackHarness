"""Regression test for the null-assistant-content sanitizer.

Strict OpenAI-compatible endpoints (Prime Inference / Qwen3.5) reject a request
whose history contains an assistant message with ``content=None`` and no
``tool_calls`` (HTTP 422: "content is required unless an assistant message
includes tool_calls or function_call"). A "thinking" model emits exactly that
when a turn is pure ``reasoning_content``. ``_sanitize_assistant_content`` must
coerce such messages to a non-null string so the rollout can continue.
"""
from __future__ import annotations

from nethack import _sanitize_assistant_content


def test_reasoning_only_assistant_gets_content():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "obs"},
        {"role": "assistant", "content": None, "tool_calls": None,
         "reasoning_content": "I should search the wall."},
    ]
    out = _sanitize_assistant_content(msgs)
    assert out[2]["content"] == "I should search the wall."


def test_empty_string_assistant_gets_placeholder():
    msgs = [{"role": "assistant", "content": "   ", "tool_calls": None}]
    out = _sanitize_assistant_content(msgs)
    assert isinstance(out[0]["content"], str) and out[0]["content"].strip() != "" or out[0]["content"] == " "
    assert out[0]["content"] == " "


def test_tool_call_assistant_left_untouched():
    msgs = [{"role": "assistant", "content": None,
             "tool_calls": [{"id": "1", "function": {"name": "search"}}]}]
    out = _sanitize_assistant_content(msgs)
    assert out[0]["content"] is None  # valid: has tool_calls


def test_user_and_normal_assistant_untouched():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "moving north"},
    ]
    out = _sanitize_assistant_content(msgs)
    assert out[0]["content"] == "hi"
    assert out[1]["content"] == "moving north"
