"""Concurrency correctness tests for the custom NetHack engine binding.

These tests are the regression guard for the fork's core purpose: multiple
independent RawEngine instances running concurrently in the same process,
including across threads.

The fork migrated NetHack's C globals into a per-context nle_ctx_t struct and
uses a thread-local current_nle_ctx pointer anchored on every C call.  These
tests prove that isolation holds under both interleaved-sequential and truly
concurrent (threaded) access patterns.

Only correctness is asserted — no timing or speedup requirements.
"""
import threading

import numpy as np
import pytest

from nethack_core import _engine

# Fixed action sequence: compass moves (h j k l y u b n) repeated.
# Raw ASCII values.
_COMPASS = [104, 108, 106, 107, 121, 117, 98, 110]
# 48 deterministic moves (each compass direction 6 times).
ACTIONS = (_COMPASS * 6)[:48]

N_ACTIONS = len(ACTIONS)


def _run_env_alone(seed: int) -> dict:
    """Run a single RawEngine for ACTIONS, return final glyphs and blstats."""
    env = _engine.RawEngine()
    env.start(core=seed, disp=seed)
    for a in ACTIONS:
        env.step(a)
    result = {
        "glyphs": env.glyphs.copy(),
        "blstats": env.blstats.copy(),
    }
    env.end()
    return result


def test_interleaved_envs_are_independent():
    """Interleaving two envs step-by-step must not corrupt either env's state.

    Protocol:
      1. Run env A (seed 1) alone for N_ACTIONS moves, capture final state.
      2. Run env B (seed 2) alone for N_ACTIONS moves, capture final state.
      3. Run both envs INTERLEAVED (step A, step B, ...) for the same moves.
      4. Assert interleaved A == alone A, interleaved B == alone B.
      5. Assert alone A != alone B (different seeds -> different state).
    """
    alone_a = _run_env_alone(seed=1)
    alone_b = _run_env_alone(seed=2)

    # Different seeds must produce different game states.
    assert not np.array_equal(alone_a["glyphs"], alone_b["glyphs"]), (
        "Seeds 1 and 2 produced identical glyphs — seeding is broken"
    )

    # Interleaved run.
    env_a = _engine.RawEngine()
    env_b = _engine.RawEngine()
    env_a.start(core=1, disp=1)
    env_b.start(core=2, disp=2)

    for a in ACTIONS:
        env_a.step(a)
        env_b.step(a)

    interleaved_a = {
        "glyphs": env_a.glyphs.copy(),
        "blstats": env_a.blstats.copy(),
    }
    interleaved_b = {
        "glyphs": env_b.glyphs.copy(),
        "blstats": env_b.blstats.copy(),
    }
    env_a.end()
    env_b.end()

    assert np.array_equal(interleaved_a["glyphs"], alone_a["glyphs"]), (
        "Interleaved env A glyphs differ from alone — context isolation broken"
    )
    assert np.array_equal(interleaved_a["blstats"], alone_a["blstats"]), (
        "Interleaved env A blstats differ from alone — context isolation broken"
    )
    assert np.array_equal(interleaved_b["glyphs"], alone_b["glyphs"]), (
        "Interleaved env B glyphs differ from alone — context isolation broken"
    )
    assert np.array_equal(interleaved_b["blstats"], alone_b["blstats"]), (
        "Interleaved env B blstats differ from alone — context isolation broken"
    )


def test_threaded_envs_are_correct():
    """N envs running concurrently on separate threads must each produce the
    same result as running alone.

    This proves that the fork's thread-local current_nle_ctx correctly isolates
    each env's C-side state under true OS-level thread concurrency.

    Correctness only — no timing or throughput assertions.
    """
    N = 6
    seeds = list(range(1, N + 1))

    # Run each env alone first to establish ground truth.
    alone = {s: _run_env_alone(seed=s) for s in seeds}

    # Shared containers for threaded results and exceptions.
    results: dict = {}
    errors: dict = {}
    lock = threading.Lock()

    def worker(seed: int) -> None:
        try:
            result = _run_env_alone(seed=seed)
            with lock:
                results[seed] = result
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors[seed] = exc

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in seeds]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    # All threads must have finished without error.
    assert not errors, (
        f"Exceptions in {len(errors)} thread(s): "
        + "; ".join(f"seed={s}: {e}" for s, e in errors.items())
    )
    assert len(results) == N, f"Only {len(results)}/{N} threads returned a result"

    # Each threaded result must match its run-alone result.
    for s in seeds:
        assert np.array_equal(results[s]["glyphs"], alone[s]["glyphs"]), (
            f"Thread seed={s} glyphs differ from alone run — thread-local isolation broken"
        )
        assert np.array_equal(results[s]["blstats"], alone[s]["blstats"]), (
            f"Thread seed={s} blstats differ from alone run — thread-local isolation broken"
        )
