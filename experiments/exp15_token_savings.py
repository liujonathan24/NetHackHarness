"""exp15 — token-savings benchmark from observation compaction.

Measures per-turn observation token cost under three configurations:
  - raw (compact=False, no history compaction): the v0.0.15-era baseline
  - obs-only compaction (compact=True): v0.0.17+
  - obs + history compaction (compact=True, post-process via _compact_chat_history): v0.0.18+

For each, runs a 60-turn autoexplore-and-search rollout and reports:
  - per-turn obs length (chars and approximate tokens)
  - cumulative prompt size after each turn (the actual LM-billed quantity)
  - cumulative savings vs baseline

The model's API bill scales with cumulative size at each turn (because the
whole history is sent every turn). So even if per-turn obs only shrinks 20%,
the cumulative growth rate gets a much bigger effect.

Approximate tokens = chars / 4 (cl100k-like). Real tokenizer would be more
accurate but adds a tiktoken dep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack import (
    _compact_chat_history,
    format_observation_as_chat,
)
from nethack_core.env import NetHackCoreEnv
from nethack_core.journal import Journal
from nethack_core.observations import shape as shape_observation
from nethack_core.skills import bootstrap_character, registry

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEED = 42
N_TURNS = 60


def _approx_tokens(s: str) -> int:
    """Quick char-count proxy for tokens. Good enough for relative comparison."""
    return len(s) // 4


def _action_indices(env, enums):
    out = []
    for e in enums:
        ev = int(e)
        for i, a in enumerate(env.unwrapped.actions):
            if int(a) == ev:
                out.append(i)
                break
    return out


def _simulate_rollout(compact: bool, with_history_compaction: bool) -> dict:
    """Run N_TURNS turns; collect obs sizes."""
    core = NetHackCoreEnv()
    core.seed(SEED, SEED)
    obs, _ = core.reset()
    character = bootstrap_character(core)
    journal = Journal()
    journal.pin_objective("explore the level")
    state: dict = {"_inv_fingerprint": None}

    structured = shape_observation(obs, character)
    chat_history: list = []
    per_turn_obs_tokens: list[int] = []
    per_turn_history_tokens: list[int] = []

    for t in range(N_TURNS):
        obs_text = format_observation_as_chat(structured, journal, state=state, compact=compact)
        per_turn_obs_tokens.append(_approx_tokens(obs_text))

        # Append to chat history.
        chat_history.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"t{t}", "type": "function", "function": {"name": "move", "arguments": '{"direction": "E"}'}}]})
        chat_history.append({"role": "user", "content": obs_text})

        # Optional history compaction (applied each turn before measurement).
        view = chat_history
        if with_history_compaction:
            view = _compact_chat_history(view, keep_full=5, drop_after=100)
        per_turn_history_tokens.append(sum(_approx_tokens(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or "") for m in view))

        # Step the env so the obs evolves.
        result = registry.call("autoexplore", core, structured, max_steps=3)
        if not result.actions:
            result = registry.call("move", core, structured, direction="E")
        indices = _action_indices(core.underlying, result.actions)
        last_obs = None
        for a in indices[:3]:
            out = core.underlying.step(a)
            last_obs = out[0]
            term = out[2]
            if term:
                break
        if last_obs is not None:
            from nethack_core.observations import CoreObservation
            structured = shape_observation(CoreObservation.from_nle(last_obs), character)

    core.close()
    return {
        "per_turn_obs_tokens": per_turn_obs_tokens,
        "per_turn_history_tokens": per_turn_history_tokens,
        "cumulative_history_tokens": per_turn_history_tokens[-1],
        "mean_per_turn_obs_tokens": round(sum(per_turn_obs_tokens) / len(per_turn_obs_tokens), 1),
    }


def run() -> dict:
    raw = _simulate_rollout(compact=False, with_history_compaction=False)
    obs_only = _simulate_rollout(compact=True, with_history_compaction=False)
    full = _simulate_rollout(compact=True, with_history_compaction=True)

    result = {
        "seed": SEED,
        "n_turns": N_TURNS,
        "raw_baseline": {
            "mean_per_turn_obs_tokens": raw["mean_per_turn_obs_tokens"],
            "cumulative_history_tokens": raw["cumulative_history_tokens"],
        },
        "obs_compaction_only": {
            "mean_per_turn_obs_tokens": obs_only["mean_per_turn_obs_tokens"],
            "cumulative_history_tokens": obs_only["cumulative_history_tokens"],
            "savings_pct_per_turn_obs": round(100 * (1 - obs_only["mean_per_turn_obs_tokens"] / max(raw["mean_per_turn_obs_tokens"], 1)), 1),
            "savings_pct_cumulative": round(100 * (1 - obs_only["cumulative_history_tokens"] / max(raw["cumulative_history_tokens"], 1)), 1),
        },
        "full_compaction": {
            "mean_per_turn_obs_tokens": full["mean_per_turn_obs_tokens"],
            "cumulative_history_tokens": full["cumulative_history_tokens"],
            "savings_pct_per_turn_obs": round(100 * (1 - full["mean_per_turn_obs_tokens"] / max(raw["mean_per_turn_obs_tokens"], 1)), 1),
            "savings_pct_cumulative": round(100 * (1 - full["cumulative_history_tokens"] / max(raw["cumulative_history_tokens"], 1)), 1),
        },
    }
    result["verdict"] = (
        "SHIPS"
        if result["obs_compaction_only"]["savings_pct_per_turn_obs"] >= 5
        and result["full_compaction"]["savings_pct_cumulative"] >= 10
        else "INCONCLUSIVE"
    )
    (OUT_DIR / "exp15_token_savings.json").write_text(json.dumps(result, indent=2))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        fig, ax = plt.subplots(figsize=(9, 4))
        x = np.arange(1, N_TURNS + 1)
        ax.plot(x, raw["per_turn_history_tokens"], label="raw baseline", color="C3", lw=2)
        ax.plot(x, obs_only["per_turn_history_tokens"], label="obs compaction only", color="C1", lw=2)
        ax.plot(x, full["per_turn_history_tokens"], label="obs + history compaction", color="C0", lw=2)
        ax.set_xlabel("turn")
        ax.set_ylabel("cumulative prompt tokens (~chars/4)")
        ax.set_title(f"exp15: cumulative LM prompt size over 60 turns (seed={SEED})")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT_DIR / "exp15_token_savings.png", dpi=120)
        plt.close(fig)
    except ImportError:
        pass

    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}")
    print(f"  Per-turn obs: {r['obs_compaction_only']['savings_pct_per_turn_obs']}% smaller (compaction)")
    print(f"  Cumulative:   {r['full_compaction']['savings_pct_cumulative']}% smaller (full compaction)")
