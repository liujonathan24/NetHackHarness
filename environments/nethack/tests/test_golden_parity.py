import os

import numpy as np
import pytest

from nethack_core import _engine

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "trace_score_seed42.npz")
FIELDS = ("tty_chars", "blstats", "message", "glyphs", "chars", "colors")


def _decode_tty(arr):
    return "\n".join(bytes(row).decode("latin1").rstrip() for row in arr)


def _first_mismatch_report(field, got, want, frame):
    lines = [f"PARITY MISMATCH field={field} frame={frame}"]
    if field in ("tty_chars",):
        lines += ["--- got ---", _decode_tty(got), "--- want ---", _decode_tty(want)]
    elif field == "blstats":
        diff = [(i, int(g), int(w)) for i, (g, w) in enumerate(zip(got, want)) if g != w]
        lines.append(f"blstats diffs (idx,got,want): {diff}")
    else:
        n = int((got != want).sum())
        lines.append(f"{n} differing cells of {got.size}")
    return "\n".join(lines)


def test_engine_matches_golden_nle():
    g = np.load(GOLDEN)
    actions = g["actions"]
    core, disp = (int(x) for x in g["seeds"])

    env = _engine.RawEngine()
    co = env.start(core=core, disp=disp).to_core_observation()

    # STAGE 1: initial-state parity (frame 0). If this fails, the setup
    # (seed/options/character/engine build) diverges before any action.
    for field in FIELDS:
        got = np.asarray(getattr(co, field))
        want = g[field][0]
        assert np.array_equal(got, want), _first_mismatch_report(field, got, want, 0)

    # STAGE 2: per-action parity.
    for i, action in enumerate(actions):
        co = env.step(int(action)).to_core_observation()
        for field in FIELDS:
            got = np.asarray(getattr(co, field))
            want = g[field][i + 1]
            assert np.array_equal(got, want), _first_mismatch_report(field, got, want, i + 1)

    env.end()
