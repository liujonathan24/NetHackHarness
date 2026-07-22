from __future__ import annotations

import json
import numpy as np
from nethack_core import glyphs as N

from nethack_harness.prompt.prompt_spec import VARIANT_REGISTRY


class _Obs:
    def __init__(self):
        g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
        g[5, 10] = N.GLYPH_MON_OFF + 20
        self.glyphs = g
        self.tty_chars = np.full((24, 80), ord(" "), np.uint8)
        b = np.zeros((27,), np.int64); b[0] = 40; b[1] = 10
        self.blstats = b


def _structured():
    # Minimal StructuredObservation-like object the template's status/inventory
    # rendering tolerates; reuse the tests/conftest make_structured_obs if present.
    from nethack_core import StructuredObservation
    return StructuredObservation(map_view="", messages=[], inventory=[],
                                 status={"hitpoints": 10, "depth": 1}, character={})


def test_json_and_toon_registered():
    assert "JSON" in VARIANT_REGISTRY
    assert "TOON" in VARIANT_REGISTRY


def test_json_variant_emits_json_text():
    spec = VARIANT_REGISTRY["JSON"]
    state = {"raw_obs": _Obs(), "map_detail": "full"}
    out = spec.turn_template(_structured(), None, state, compact=True, journal_max_chars=2000)
    assert isinstance(out, str)
    assert '"entities"' in out  # JSON payload present


def test_map_detail_minimal_smaller_than_full():
    spec = VARIANT_REGISTRY["JSON"]
    obs = _Obs(); s = _structured()
    full = spec.turn_template(s, None, {"raw_obs": obs, "map_detail": "full"},
                              compact=True, journal_max_chars=2000)
    mini = spec.turn_template(s, None, {"raw_obs": obs, "map_detail": "minimal"},
                              compact=True, journal_max_chars=2000)
    assert len(mini) < len(full)
