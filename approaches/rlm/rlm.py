"""
approaches.rlm.rlm
==================

RLM (Recursive Language Models) driver for NetHack — a code-mode rollout that
decomposes long-horizon reasoning by recursively calling sub-LMs over slices of
context (cf. Recursive Language Models, Zhang/Kraska/Khattab, arXiv:2512.24601;
and the BALROG RLM env).

What this is
------------
Each turn we run a block of Python *source* against the curated ``nh`` namespace
(``nethack_harness.tools.code_mode``), collect the NLE actions the source asked
to take, apply them to the live engine, re-observe, and continue — for N turns.

The *recursive* part: the source calls the sub-LM tools
(``nh.plan`` / ``nh.summarize`` / ``nh.recall_lm``) to break long-horizon
planning into sub-problems. Those tools route through a ``SubLM`` backend.

KEYLESS smoke
-------------
For the smoke we do NOT need a real top-level LLM authoring the source. We drive
the loop with a fixed scripted "RLM program" (``RLM_PROGRAM`` below) — a snippet
of ``nh``-namespace Python that (a) calls ``nh.plan(...)`` (sub-LM), (b) acts on
the plan via ``nh.autoexplore()`` / ``nh.descend()`` / ``nh.move(...)``, and
(c) calls ``nh.summarize(...)`` to compress state into a journal note. Running
this each turn exercises the FULL recursive-LM plumbing (safe code execution +
sub-LM calls + acting) using the deterministic offline ``SubLM`` stub — zero API
cost.

Backends
--------
``--backend offline`` (default): the offline ``OfflineSubLM`` stub. Deterministic,
no network, zero cost. Use this for the smoke.

``--backend glm``: a real ``SubLM`` backed by GLM (``z-ai/glm-5``) via the
OpenAI-compatible Prime Inference endpoint. Credentials resolve from the same
env vars the refiner uses: ``REFINER_API_KEY`` (key) and ``REFINER_BASE_URL``
(endpoint). NOT exercised in the smoke (no budget).

Why this file re-implements a tiny executor
--------------------------------------------
``code_mode.run_user_code`` does not (yet) accept a ``sub_lm=`` argument — it
always constructs the offline stub internally. Rather than edit code_mode.py
(out of scope here), we reuse its public, audited pieces — ``validate_source``,
the ``_NhNamespace`` (which *does* accept ``sub_lm=``), ``_safe_builtins``,
``_DIRECTIONS`` / ``_Position`` — and run the same validate→exec→collect-actions
flow ourselves. This keeps the safety policy identical while letting us thread an
arbitrary ``SubLM`` (offline or GLM) through ``nh.plan/summarize/recall_lm``.

CLI
---
    python -m approaches.rlm.rlm --turns 8 --seed 2 --backend offline
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nethack_core import NetHackCoreEnv
from nethack_core import shape as shape_observation
from nethack_harness.tools.code_mode import (
    CodeModeError,
    OfflineSubLM,
    SubLM,
    _DIRECTIONS,
    _NhNamespace,
    _Position,
    _safe_builtins,
    validate_source,
)
from nethack_harness.tools.skills import bootstrap_character

log = logging.getLogger("rlm")

# blstats indices (mirrors observations.BLSTATS_IDX; duplicated here so the
# driver can read depth/pos straight off the raw obs without re-shaping).
_BL_X, _BL_Y, _BL_DEPTH = 0, 1, 12


# ---------------------------------------------------------------------------
# The scripted RLM program.
#
# This is the snippet of ``nh``-namespace Python we run each turn in the keyless
# smoke. A real RLM would have the top-level LLM *author* this each turn; here we
# fix it so the run is deterministic and free. It exercises every limb of the
# recursive-LM loop:
#
#   1. nh.plan(objective)            -> sub-LM call (decompose long horizon)
#   2. nh.recall_lm(query)           -> sub-LM call (memory retrieval over notes)
#   3. act on the plan: descend if standing on '>' else autoexplore, then a
#      directional nudge — these enqueue NLE actions the driver flushes.
#   4. nh.summarize(state_slice)     -> sub-LM call (compress state to a note)
#   5. nh.add_note(...)              -> persist the belief-state summary
#
# It is deliberately defensive (everything wrapped so a missing field never
# aborts the turn) and uses only the allow-listed builtins.
# ---------------------------------------------------------------------------
RLM_PROGRAM = r'''
# --- recursive planning over a long horizon (sub-LM) ---
plan = nh.plan("descend as deep as possible while staying alive", horizon=4)
print("PLAN:")
for step in plan:
    print("  -", step)

# --- recursive memory retrieval (sub-LM over journal notes) ---
memo = nh.recall_lm("what is the current descent objective?")
print("RECALL:", memo)

# --- act on the plan ---
under = nh.under_player or ""
on_down_stairs = "DOWN" in str(under)
if on_down_stairs:
    print("ACT: on down-stairs -> descend()")
    nh.descend()
else:
    print("ACT: explore the level -> autoexplore()")
    nh.autoexplore(max_steps=20)

# A small directional nudge toward any visible down-stairs in the adjacency,
# else a default step east. Demonstrates nh.move + reading structured obs.
adj = nh.adjacent or {}
stair_dir = None
for d, label in adj.items():
    if "stairs DOWN" in str(label):
        stair_dir = d
        break
if stair_dir is not None:
    print("ACT: down-stairs adjacent (%s) -> move(%s)" % (stair_dir, stair_dir))
    nh.move(stair_dir)

# --- compress current state into a belief-state note (sub-LM) ---
st = nh.status or {}
state_slice = "depth=%s hp=%s/%s pos=(%s,%s) map_head=%s" % (
    st.get("depth"), st.get("hitpoints"), st.get("max_hitpoints"),
    st.get("x"), st.get("y"), (nh.map_view or "").splitlines()[:1],
)
summary = nh.summarize(state_slice, query="belief state for descent")
print("SUMMARY:", summary)
nh.add_note("belief_state", summary)
'''


# ---------------------------------------------------------------------------
# A tiny in-memory journal (nh.add_note / nh.recall / recall_lm read this).
# ---------------------------------------------------------------------------
class _Journal:
    """Minimal journal so nh.add_note / nh.recall / nh.recall_lm work without
    pulling in the full verifiers state. Notes are a dict; recall is substring."""

    def __init__(self) -> None:
        self.notes: dict[str, str] = {}
        self.objective: Optional[str] = None

    def add_note(self, key: str, text: str) -> None:
        self.notes[str(key).strip().lower()] = str(text)

    def recall(self, query: str) -> list[str]:
        q = (query or "").lower()
        hits = [v for k, v in self.notes.items() if q in k or q in v.lower()]
        return hits or list(self.notes.values())

    def pin_objective(self, objective: str) -> None:
        self.objective = objective


# ---------------------------------------------------------------------------
# GLM sub-LM backend (OpenAI-compatible Prime Inference endpoint).
# ---------------------------------------------------------------------------
class GLMSubLM(SubLM):
    """Real ``SubLM`` backed by GLM via an OpenAI-compatible endpoint.

    Credentials mirror ``nethack_harness.refiner`` resolution:
        REFINER_API_KEY   -> api key      (required)
        REFINER_BASE_URL  -> endpoint url (Prime Inference, OpenAI-compatible)
        REFINER_TIMEOUT_S -> request timeout (default 30s)

    Model id defaults to ``z-ai/glm-5``. Each sub-tool is one short chat call.
    This backend is NOT exercised in the keyless smoke (it would cost tokens).
    """

    def __init__(
        self,
        model: str = "z-ai/glm-5",
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.model = model
        self.base_url = base_url or os.getenv("REFINER_BASE_URL")
        self.api_key = api_key or os.getenv("REFINER_API_KEY")
        self.timeout_s = float(os.getenv("REFINER_TIMEOUT_S", timeout_s))
        if not self.api_key:
            raise RuntimeError(
                "GLMSubLM requires an API key. Set REFINER_API_KEY (and "
                "REFINER_BASE_URL for the Prime Inference endpoint). Use "
                "--backend offline for a keyless run."
            )
        from openai import OpenAI  # lazy: keeps offline path import-light

        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _chat(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=self.timeout_s,
        )
        return (resp.choices[0].message.content or "").strip()

    def summarize(self, text: str, query: Optional[str] = None) -> str:
        sys = "You compress NetHack state into a one-line belief-state note."
        q = f" Focus: {query}." if query else ""
        return self._chat(sys, f"Summarize in one line.{q}\n\n{text}")

    def plan(self, objective: str, horizon: int = 5) -> list[str]:
        sys = (
            "You are a NetHack strategist. Output a short ordered plan, one step "
            "per line, no numbering, concrete actions only."
        )
        out = self._chat(sys, f"Objective: {objective}\nGive at most {horizon} steps.")
        steps = [ln.strip(" -*\t") for ln in out.splitlines() if ln.strip()]
        return steps[:horizon] or [f"toward: {objective}"]

    def recall(self, query: str, context: str = "") -> str:
        sys = "Answer the query using only the provided notes; be terse."
        return self._chat(sys, f"Notes:\n{context}\n\nQuery: {query}")


def make_sub_lm(backend: str) -> SubLM:
    """Construct the sub-LM backend. 'offline' = deterministic stub (zero cost);
    'glm' = live GLM via Prime Inference (creds from REFINER_API_KEY/BASE_URL)."""
    if backend == "offline":
        return OfflineSubLM()
    if backend == "glm":
        return GLMSubLM()
    raise ValueError(f"unknown backend {backend!r} (expected 'offline' or 'glm')")


# ---------------------------------------------------------------------------
# Code execution with a threaded SubLM (re-uses code_mode's audited pieces).
# ---------------------------------------------------------------------------
@dataclass
class _TurnResult:
    stdout: str
    error: Optional[str]
    actions: list[int] = field(default_factory=list)
    sub_lm_calls: list[str] = field(default_factory=list)


class _CountingSubLM(SubLM):
    """Wraps a SubLM and records which sub-tools were invoked (for verification
    + tracing). Delegates everything to the wrapped backend."""

    def __init__(self, inner: SubLM) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def summarize(self, text: str, query: Optional[str] = None) -> str:
        self.calls.append("summarize")
        return self._inner.summarize(text, query=query)

    def plan(self, objective: str, horizon: int = 5) -> list[str]:
        self.calls.append("plan")
        return self._inner.plan(objective, horizon=horizon)

    def recall(self, query: str, context: str = "") -> str:
        self.calls.append("recall")
        return self._inner.recall(query, context=context)


def run_rlm_source(
    source: str,
    env,
    structured_obs,
    *,
    journal,
    raw_obs,
    sub_lm: SubLM,
    timeout_seconds: int = 5,
) -> _TurnResult:
    """Validate + execute ``source`` against the ``nh`` namespace with a threaded
    ``sub_lm``. Mirrors ``code_mode.run_user_code`` but lets us pass the backend.

    Returns the captured stdout, any error string, the queued NLE actions, and
    the list of sub-LM tools that were invoked this turn.
    """
    try:
        validate_source(source)
    except CodeModeError as e:
        return _TurnResult(stdout="", error=str(e))

    counting = _CountingSubLM(sub_lm)
    nh = _NhNamespace(env, structured_obs, journal, raw_obs=raw_obs, sub_lm=counting)
    namespace = {
        "nh": nh,
        "Direction": _DIRECTIONS,
        "Position": _Position,
        "__builtins__": _safe_builtins(),
    }

    buf = io.StringIO()
    error: Optional[str] = None

    def _alarm(_s, _f):
        raise CodeModeError(f"Code timed out after {timeout_seconds}s.")

    have_alarm = hasattr(signal, "SIGALRM")
    if have_alarm:
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(timeout_seconds)
    try:
        with contextlib.redirect_stdout(buf):
            exec(source, namespace)  # noqa: S102 — sandboxed via validate_source
    except CodeModeError as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001 — surface any runtime error to the trace
        error = f"{type(e).__name__}: {e}"
    finally:
        if have_alarm:
            signal.alarm(0)

    return _TurnResult(
        stdout=buf.getvalue(),
        error=error,
        actions=list(nh._log),
        sub_lm_calls=list(counting.calls),
    )


# ---------------------------------------------------------------------------
# Observation helpers.
# ---------------------------------------------------------------------------
def _depth_pos(raw_obs) -> tuple[int, int, int]:
    try:
        b = raw_obs.blstats
        return int(b[_BL_DEPTH]), int(b[_BL_X]), int(b[_BL_Y])
    except Exception:
        return 0, 0, 0


def _grid_text(raw_obs) -> str:
    """ASCII dungeon grid from the raw obs chars (21x79)."""
    try:
        rows = ["".join(chr(int(c)) for c in row) for row in raw_obs.chars]
        return "\n".join(r.rstrip() for r in rows)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Rollout.
# ---------------------------------------------------------------------------
def run_rollout(
    *,
    turns: int,
    seed: int,
    backend: str,
    task_name: str = "NetHackScore-v0",
    out_root: Optional[Path] = None,
) -> dict:
    """Run the scripted RLM code-mode rollout for ``turns`` turns.

    Writes one NDJSON line per turn to
    ``environments/nethack/outputs/web_play/rlm_seed<seed>/trace.ndjson`` and
    returns a small summary dict (advanced?, depth/pos deltas, sub-LM call tally).
    """
    sub_lm = make_sub_lm(backend)

    if out_root is None:
        out_root = (
            Path(__file__).resolve().parents[2]
            / "environments" / "nethack" / "outputs" / "web_play"
        )
    out_dir = out_root / f"rlm_seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.ndjson"

    env = NetHackCoreEnv(task_name=task_name)
    env.seed(core=seed, disp=seed)
    raw_obs, meta = env.reset()
    character = bootstrap_character(env)
    journal = _Journal()
    journal.pin_objective("descend as deep as possible")

    structured_obs = shape_observation(raw_obs, character)

    d0, x0, y0 = _depth_pos(raw_obs)
    total_sub_calls: dict[str, int] = {}
    turn_records: list[dict] = []
    done = False

    log.info("RLM rollout start: seed=%s backend=%s turns=%s char=%s",
             seed, backend, turns, character)

    with trace_path.open("w") as tf:
        for turn in range(1, turns + 1):
            res = run_rlm_source(
                RLM_PROGRAM, env, structured_obs,
                journal=journal, raw_obs=raw_obs, sub_lm=sub_lm,
            )
            for c in res.sub_lm_calls:
                total_sub_calls[c] = total_sub_calls.get(c, 0) + 1

            # Apply the queued actions to the live engine.
            applied = 0
            for act in res.actions:
                if done:
                    break
                try:
                    raw_obs, _r, term, trunc, _info = env.step(int(act))
                    applied += 1
                    if term or trunc:
                        done = True
                        break
                except Exception as e:  # noqa: BLE001
                    log.warning("env.step(%s) failed: %s", act, e)
                    break

            structured_obs = shape_observation(raw_obs, character)
            depth, px, py = _depth_pos(raw_obs)

            record = {
                "turn": turn,
                "variant": "B1",
                "backend": backend,
                "seed": seed,
                "depth": depth,
                "pos": [px, py],
                "actions_queued": len(res.actions),
                "actions_applied": applied,
                "sub_lm_calls": res.sub_lm_calls,
                "code_error": res.error,
                "code_stdout": res.stdout,
                "raw_grid": _grid_text(raw_obs),
                "rendered_user_content": _render_user_content(
                    structured_obs, res, depth, px, py
                ),
                "done": done,
            }
            tf.write(json.dumps(record) + "\n")
            tf.flush()
            turn_records.append(record)

            log.info(
                "turn %02d | depth=%s pos=(%s,%s) | sub_lm=%s | acts %d/%d | err=%s",
                turn, depth, px, py, res.sub_lm_calls, applied,
                len(res.actions), res.error,
            )
            if done:
                log.info("game ended at turn %d", turn)
                break

    with contextlib.suppress(Exception):
        env.close()

    d_last, x_last, y_last = _depth_pos(raw_obs)
    advanced = (d_last != d0) or (x_last != x0) or (y_last != y0)

    summary = {
        "seed": seed,
        "backend": backend,
        "turns_run": len(turn_records),
        "start": {"depth": d0, "pos": [x0, y0]},
        "end": {"depth": d_last, "pos": [x_last, y_last]},
        "advanced": advanced,
        "sub_lm_call_totals": total_sub_calls,
        "trace_path": str(trace_path),
        "done": done,
    }
    return summary


def _render_user_content(structured_obs, res: _TurnResult, depth, px, py) -> str:
    """A compact B1-style text block: obs digest + sub-LM outputs + actions.

    Full B1 chat rendering lives in the verifiers env; here we dump the obs text,
    the sub-LM-driven program output, and the action tally so the turn is
    inspectable from the trace alone."""
    lines = [
        f"=== TURN (depth={depth} pos=({px},{py})) ===",
        "--- MAP ---",
        (structured_obs.map_view or "").rstrip(),
        f"--- STATUS --- {structured_obs.status}",
        f"--- UNDER PLAYER --- {structured_obs.under_player}",
        f"--- ADJACENT --- {structured_obs.adjacent}",
        "--- RLM PROGRAM OUTPUT (sub-LM driven) ---",
        res.stdout.rstrip(),
        f"--- SUB-LM TOOLS INVOKED --- {res.sub_lm_calls}",
        f"--- ACTIONS QUEUED --- {res.actions}",
    ]
    if res.error:
        lines.append(f"--- CODE ERROR --- {res.error}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="RLM code-mode NetHack rollout.")
    p.add_argument("--turns", type=int, default=8, help="number of RLM turns")
    p.add_argument("--seed", type=int, default=2, help="env seed (core==disp)")
    p.add_argument(
        "--backend", choices=["offline", "glm"], default="offline",
        help="sub-LM backend: 'offline' (keyless stub, default) or 'glm' "
             "(live GLM via Prime Inference; needs REFINER_API_KEY/BASE_URL)",
    )
    p.add_argument("--task", default="NetHackScore-v0", help="NLE task name")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )
    # Always show the rlm logger at INFO so the smoke prints turn-by-turn.
    log.setLevel(logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    t0 = time.time()
    summary = run_rollout(
        turns=args.turns, seed=args.seed, backend=args.backend,
        task_name=args.task,
    )
    summary["wall_s"] = round(time.time() - t0, 2)

    print("\n=== RLM ROLLOUT SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(
        "\nGAME ADVANCED:" if summary["advanced"] else "\nGAME DID NOT ADVANCE:",
        f"depth {summary['start']['depth']}->{summary['end']['depth']}, "
        f"pos {summary['start']['pos']}->{summary['end']['pos']}",
    )
    print("SUB-LM TOOLS INVOKED:", summary["sub_lm_call_totals"])
    print("TRACE:", summary["trace_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
