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


# ---------------------------------------------------------------------------
# Task 3: IMG / IMG_TTY variant registration + multimodal template
# ---------------------------------------------------------------------------
import numpy as np

from nethack_harness.prompt.prompt_spec import VARIANT_REGISTRY


class _Obs:
    def __init__(self):
        self.glyphs = np.zeros((21, 79), dtype=np.int32)
        self.tty_chars = np.full((24, 80), ord(" "), dtype=np.uint8)
        self.tty_colors = np.zeros((24, 80), dtype=np.uint8)


def test_img_and_img_tty_registered():
    assert "IMG" in VARIANT_REGISTRY
    assert "IMG_TTY" in VARIANT_REGISTRY
    assert VARIANT_REGISTRY["IMG"].obs.mode == "img"
    assert VARIANT_REGISTRY["IMG_TTY"].obs.mode == "img"


def test_img_template_emits_multimodal_list(make_structured_obs):
    spec = VARIANT_REGISTRY["IMG"]
    state = {"raw_obs": _Obs()}
    content = spec.turn_template(
        make_structured_obs(), None, state, compact=True, journal_max_chars=2000
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"
    # IMG text is journal+status+inventory only — no map/adjacent/under-player
    assert "=== MAP ===" not in content[1]["text"]
    assert "=== ADJACENT ===" not in content[1]["text"]
    assert "=== STATUS ===" in content[1]["text"]
