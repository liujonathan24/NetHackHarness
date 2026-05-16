"""Tests for the history-compaction override in NetHackVerifiersEnv.

The override is the single biggest token-bill lever (see docs/PROMPTING_SURVEY.md
recommendation #1: stop echoing past tty grids). Three tiers:
  - last K=5 turns: full content
  - turns 6..100: replaced with one-line summary
  - turns >100: dropped entirely
"""
from __future__ import annotations

import verifiers as vf

from nethack import _compact_chat_history, _msg_content, _msg_role, _one_line_summary


def _user(content: str):
    return vf.UserMessage(role="user", content=content)


def _assistant(content: str = ""):
    return vf.AssistantMessage(role="assistant", content=content, tool_calls=[])


def test_short_history_passes_through_unchanged():
    msgs = [_user("sys"), _assistant(), _user("turn 1"), _assistant(), _user("turn 2")]
    out = _compact_chat_history(msgs, keep_full=5, drop_after=100)
    assert len(out) == len(msgs)
    assert out[2].content == "turn 1"


def test_older_user_messages_get_summarized():
    """With keep_full=2 and 5 user messages, the first 3 should be summarized."""
    msgs = []
    for i in range(5):
        msgs.append(_user(f"TURN {i}\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10  AC: 9  Dlvl: 1  Turn: {i}"))
        msgs.append(_assistant())
    out = _compact_chat_history(msgs, keep_full=2, drop_after=100)
    # User messages indices: 0,2,4,6,8 — last 2 kept, first 3 summarized.
    user_msgs = [m for m in out if m.role == "user"]
    # First 3 should be compacted (no MAP block), last 2 still full.
    assert "=== MAP ===" not in user_msgs[0].content
    assert "=== MAP ===" not in user_msgs[1].content
    assert "=== MAP ===" not in user_msgs[2].content
    assert "=== MAP ===" in user_msgs[3].content
    assert "=== MAP ===" in user_msgs[4].content


def test_very_old_messages_dropped_with_elision_marker():
    """With drop_after=3 and 10 user messages, the oldest ones should be dropped
    and replaced with a single elision marker."""
    msgs = []
    for i in range(10):
        msgs.append(_user(f"turn {i}: some content"))
        msgs.append(_assistant())
    out = _compact_chat_history(msgs, keep_full=2, drop_after=3)
    # keep_full=2 means last 2 full; drop_after=3 means anything beyond turn -3
    # gets dropped. 10 user msgs - 2 kept - up-to-1 compacted = 7 dropped.
    user_msgs = [m for m in out if m.role == "user"]
    # First should be the elision marker.
    assert "elided" in user_msgs[0].content
    # Should have far fewer user messages than original 10.
    assert len(user_msgs) < 10


def test_summary_preserves_status_line():
    full = """=== MAP ===
@..
=== STATUS ===
HP: 7/10  AC: 6  Dlvl: 3  Turn: 42  XP: 2  $: 5
=== MESSAGES ===
  You hit the kobold."""
    summary = _one_line_summary(full, turn_distance=10)
    assert "HP: 7/10" in summary
    assert "Dlvl: 3" in summary
    assert "[turn -10]" in summary
    # Should be shorter than original.
    assert len(summary) < len(full)


def test_summary_preserves_feedback_prefix():
    full = "[autohalt: HP dropped 10->5]\n\n=== MAP ===\n@..\n=== STATUS ===\nHP: 5/10  AC: 9"
    summary = _one_line_summary(full, turn_distance=8)
    assert "autohalt" in summary


def test_compaction_does_not_mutate_input():
    """Returns a new list; input is untouched."""
    msgs = [_user("t1"), _assistant(), _user("t2"), _assistant(), _user("t3"),
            _assistant(), _user("t4"), _assistant(), _user("t5"), _assistant(),
            _user("t6"), _assistant()]
    snapshot = [m.content for m in msgs]
    out = _compact_chat_history(msgs, keep_full=2, drop_after=100)
    assert [m.content for m in msgs] == snapshot
    assert out is not msgs


def test_compaction_is_idempotent_no_chain_accumulation():
    """Regression: compacting already-compacted messages must NOT prepend
    a new `[turn -K]` to the existing label chain. Bug found 2026-05-16
    via user trace: messages became `[turn -92] [turn -91] ... [turn -7]`
    with no content after many turns."""
    # Build 8 user turns; compaction with keep_full=2 should compact 6.
    msgs = []
    for i in range(8):
        msgs.append(_user(f"TURN {i}\n=== MAP ===\n@\n=== STATUS ===\nHP: 10/10 AC: 9 Dlvl: 1 Turn: {i}"))
        msgs.append(_assistant())
    out1 = _compact_chat_history(msgs, keep_full=2, drop_after=100)

    # Now simulate the next turn: the compacted output (out1) becomes input
    # to the next call (after a new turn appended).
    out1_with_new_turn = list(out1) + [
        _user(f"TURN 8\n=== MAP ===\n@\n=== STATUS ===\nHP: 10/10 AC: 9 Dlvl: 1 Turn: 8"),
        _assistant(),
    ]
    out2 = _compact_chat_history(out1_with_new_turn, keep_full=2, drop_after=100)
    # And the next:
    out2_with_new_turn = list(out2) + [
        _user(f"TURN 9\n=== MAP ===\n@\n=== STATUS ===\nHP: 10/10 AC: 9 Dlvl: 1 Turn: 9"),
        _assistant(),
    ]
    out3 = _compact_chat_history(out2_with_new_turn, keep_full=2, drop_after=100)

    # No user message should contain a chain of more than one turn label.
    for m in out3:
        if _msg_role(m) == "user":
            content = _msg_content(m)
            count = content.count("[turn -")
            assert count <= 1, (
                f"Chain accumulation bug returned: a user message contains "
                f"{count} [turn -N] labels: {content[:200]}"
            )


def test_dict_shaped_messages_compact():
    """Backward-compat: dict-shaped messages should also compact."""
    msgs = [
        {"role": "user", "content": "TURN 0\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "TURN 1\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "TURN 2\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "TURN 3\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "TURN 4\n=== MAP ===\n@..\n=== STATUS ===\nHP: 10/10"},
    ]
    out = _compact_chat_history(msgs, keep_full=2, drop_after=100)
    user_msgs = [m for m in out if m["role"] == "user"]
    # Last 2 kept, earlier compacted (no MAP).
    assert "=== MAP ===" not in user_msgs[0]["content"]
    assert "=== MAP ===" in user_msgs[-1]["content"]
