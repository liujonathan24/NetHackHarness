"""Tests for the IMG / IMG_TTY observation variants.

This file (formatter portion) covers the `include_map` / `include_local` gates on
`format_observation_as_chat`. The `make_structured_obs` fixture lives in
`tests/conftest.py`.
"""
from __future__ import annotations

from nethack_harness.prompt.rendering import format_observation_as_chat


def test_include_map_false_drops_map_block(make_structured_obs):
    s = make_structured_obs()
    full = format_observation_as_chat(s, None, None, compact=False)
    no_map = format_observation_as_chat(s, None, None, compact=False, include_map=False)
    assert "=== MAP ===" in full
    assert "=== MAP ===" not in no_map
    # status / inventory still present
    assert "=== STATUS ===" in no_map


def test_include_local_false_drops_local_blocks(make_structured_obs):
    s = make_structured_obs()
    no_local = format_observation_as_chat(
        s, None, None, compact=False, include_map=False, include_local=False
    )
    assert "=== ADJACENT ===" not in no_local
    assert "=== UNDER PLAYER ===" not in no_local


def test_defaults_unchanged(make_structured_obs):
    s = make_structured_obs()
    a = format_observation_as_chat(s, None, None, compact=False)
    b = format_observation_as_chat(
        s, None, None, compact=False, include_map=True, include_local=True
    )
    assert a == b  # defaults must be byte-identical
