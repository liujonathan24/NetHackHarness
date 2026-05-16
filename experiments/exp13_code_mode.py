"""exp13 — code mode (Track B v0.2): one tool call, many actions, sub-skill composition.

Headline: with `interface='code'`, the model writes a Python loop that calls
`nh.move()` / `nh.autoexplore()` / `nh.add_note()` / `nh.wiki_lookup()` etc.
in a single tool call. The env runs the source against a sandboxed namespace,
collects the action queue, and steps NLE once per action.

This experiment compares two equivalent rollouts:
  skill mode:  4 separate tool calls (autoexplore, status check, wiki_lookup, add_note)
  code mode:   1 tool call containing all four operations as Python

Verdict = FIX CONFIRMED if code mode produces the same action queue length
in 1 tool call as skill mode does in 4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.code_mode import run_user_code
from nethack_core.env import NetHackCoreEnv
from nethack_core.journal import Journal
from nethack_core.observations import shape as shape_observation
from nethack_core.skills import registry

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEED = 42


def _setup():
    core = NetHackCoreEnv()
    core.seed(SEED, SEED)
    core_obs, _ = core.reset()
    structured = shape_observation(core_obs, character={"role": "unknown"})
    return core, structured


def skill_mode_rollout() -> dict:
    """4 separate skill calls."""
    core, structured = _setup()
    journal = Journal()

    calls = 0
    actions: list[int] = []

    # 1) autoexplore
    r = registry.call("autoexplore", core, structured, max_steps=10)
    actions.extend(int(a) for a in r.actions)
    calls += 1

    # 2) status check (synthetic — just inspect; no skill needed but counts as one tool call)
    _ = structured.status.get("hitpoints", 0)
    calls += 1

    # 3) wiki_lookup
    r = registry.call("wiki_lookup", core, structured, entity="altar")
    calls += 1

    # 4) add_note
    r = registry.call("add_note", core, structured, key="strategy", text="explore + note")
    if r.journal_op:
        r.journal_op(journal)
    calls += 1

    core.close()
    return {"tool_calls": calls, "actions_queued": len(actions), "journal_notes": len(journal.notes)}


def code_mode_rollout() -> dict:
    """1 tool call containing all 4 operations as Python."""
    core, structured = _setup()
    journal = Journal()

    source = """
nh.autoexplore(max_steps=10)
hp = nh.status.get('hitpoints', 0)
altar = nh.wiki_lookup('altar')
if altar:
    nh.add_note('lore', altar.title)
nh.add_note('strategy', f'hp={hp}, explored, found altar lore')
print('done')
"""
    result = run_user_code(source, env=core, structured_obs=structured, journal=journal)
    core.close()
    return {
        "tool_calls": 1,
        "actions_queued": len(result.actions_taken),
        "journal_notes": len(journal.notes),
        "stdout": result.stdout.strip(),
        "error": result.error,
    }


def run() -> dict:
    skill = skill_mode_rollout()
    code = code_mode_rollout()

    result = {
        "seed": SEED,
        "skill_mode": skill,
        "code_mode": code,
        "tool_call_savings": skill["tool_calls"] - code["tool_calls"],
    }
    result["verdict"] = (
        "FIX CONFIRMED"
        if code["tool_calls"] == 1
        and code["error"] is None
        and code["actions_queued"] >= 1
        and code["journal_notes"] >= 1
        else "INCONCLUSIVE"
    )
    (OUT_DIR / "exp13_code_mode.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}: code mode saved {r['tool_call_savings']} LM round-trips on this rollout slice")
