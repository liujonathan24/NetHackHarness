"""
approaches.voyager.voyager
==========================

Voyager driver for NetHack: an automatic-curriculum + skill-library agent
(after *Voyager: An Open-Ended Embodied Agent with LLMs*, Wang et al. 2023),
grounded in this repo's existing skill registry and refiner persistence format.

The loop (one iteration):

  1. PROPOSE OBJECTIVE  — the Proposer reads a state summary + the names of
     already-learned skills and proposes the next objective (a NL string plus a
     structured success predicate).
  2. SYNTHESIZE SKILL   — the Proposer emits a *named macro*: an ordered list of
     `MacroStep` (existing primitive skills with args). A macro is exactly the
     `K` (skills) component the continual-harness refiner edits.
  3. EXECUTE + VERIFY   — run the macro on the env (one `registry.call` per
     step), re-observing after each step; then evaluate the objective's success
     predicate against the before/after state.
  4. STORE              — on success, add the macro to the persistent skill
     library (keyed by name); on failure, record it and feed the failure back
     into the next proposal round.

The skill library is persisted to JSON in the SAME shape `refiner.snapshot_components`
uses for its `skills` field — a dict `name -> list[{"skill", "args"}]` — so the
library is a drop-in `bootstrap_dir` skills blob that carries across episodes and
can be loaded by `refiner.load_components`.

Two Proposer implementations, selected with `--proposer`:

  * stub  (default, KEYLESS, ZERO cost) — a deterministic proposer that cycles
    through a few sensible objectives and emits fixed macros over the primitive
    skills. Used for the smoke test.
  * glm   — a GLM-backed proposer (`z-ai/glm-5` via Prime Inference, creds from
    REFINER_API_KEY / REFINER_BASE_URL, mirroring refiner.py). Wired but NOT
    exercised in the smoke (no API budget).

CLI:
    python -m approaches.voyager.voyager --iterations 6 --seed 2 --proposer stub
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

# These imports require PYTHONPATH to include the repo root and the nethack env:
#   PYTHONPATH="$PWD:$PWD/environments/nethack"
from nethack_core import NetHackCoreEnv
from nethack_core import shape as shape_observation
from nethack_harness.refiner import MacroStep
from nethack_harness.tools.skills import (
    bootstrap_character,
    list_skills,
    registry,
)

log = logging.getLogger("voyager")


# --------------------------------------------------------------------------
# Objective / proposal payloads
# --------------------------------------------------------------------------


@dataclass
class Objective:
    """One curriculum objective + the macro proposed to achieve it.

    `success_predicate` is a small, safe-to-evaluate descriptor:
        {"kind": "dlvl_increase"}        — success if depth strictly increased
        {"kind": "dlvl_at_least", "n": 2}
        {"kind": "inventory_grew"}       — success if inventory item count grew
        {"kind": "level_explored"}       — success if the macro ran without
                                            error (best-effort exploration goal)
    The evaluator (`_check_success`) refuses unknown kinds (fail-closed).
    """

    name: str
    description: str
    macro: list[MacroStep]
    success_predicate: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateSummary:
    """Compact, JSON-safe snapshot of the agent's situation fed to the Proposer."""

    dlvl: int
    max_dlvl: int
    hp: int
    hp_max: int
    inventory_count: int
    learned_skills: list[str]
    recent_failures: list[str]

    def to_dict(self) -> dict:
        return {
            "dlvl": self.dlvl,
            "max_dlvl": self.max_dlvl,
            "hp": self.hp,
            "hp_max": self.hp_max,
            "inventory_count": self.inventory_count,
            "learned_skills": self.learned_skills,
            "recent_failures": self.recent_failures[-5:],
        }


# --------------------------------------------------------------------------
# Proposer protocol + implementations
# --------------------------------------------------------------------------


class Proposer(Protocol):
    def propose(self, summary: StateSummary) -> Objective:
        """Given the current state summary, propose the next objective + macro."""
        ...


# Valid primitive skill names the macros may compose. Resolved once against the
# live registry so a macro can never name a skill that doesn't exist.
def _valid_skills() -> set[str]:
    try:
        return set(list_skills())
    except Exception:
        return set()


class StubProposer:
    """Deterministic, KEYLESS proposer used for the smoke (zero API cost).

    Cycles through three sensible objectives and emits a fixed macro for each:

      * "descend one level"          -> [explore_and_descend]   (dlvl_increase)
      * "explore the floor"          -> [autoexplore, autoexplore]  (level_explored)
      * "search for hidden passages" -> [search(times=10)]      (level_explored)

    The descend objective is the one that grows max dlvl and reliably fires its
    success predicate; the other two demonstrate macro composition over multiple
    primitive skills.
    """

    def __init__(self) -> None:
        self._i = 0

    def propose(self, summary: StateSummary) -> Objective:
        cycle = [
            Objective(
                name="dive_one_floor",
                description="Descend one level deeper into the dungeon.",
                macro=[
                    MacroStep(
                        skill="explore_and_descend",
                        args={"max_floors": 1, "max_game_steps": 600},
                    )
                ],
                success_predicate={"kind": "dlvl_increase"},
            ),
            Objective(
                name="sweep_floor",
                description="Explore the current floor to reveal rooms and corridors.",
                macro=[
                    MacroStep(skill="autoexplore", args={"max_steps": 30}),
                    MacroStep(skill="autoexplore", args={"max_steps": 30}),
                ],
                success_predicate={"kind": "level_explored"},
            ),
            Objective(
                name="probe_hidden_passages",
                description="Search nearby walls for hidden passages and traps.",
                macro=[MacroStep(skill="search", args={"times": 10})],
                success_predicate={"kind": "level_explored"},
            ),
        ]
        obj = cycle[self._i % len(cycle)]
        self._i += 1
        return obj


_GLM_SYSTEM_PROMPT = """You are the curriculum + skill-synthesis brain of a Voyager agent playing NetHack.
You DO NOT play directly. Instead, every round you (1) propose the next objective
appropriate to the agent's current state (biased toward novelty / making progress)
and (2) compose a NAMED MACRO that achieves it, using ONLY the existing primitive
skills listed below (no model-authored code).

Primitive skills available (compose these, with their documented args):
%(skills)s

Respond with STRICT JSON only, matching this schema:
{
  "objective": "<short natural-language goal>",
  "name": "<snake_case macro name>",
  "macro": [ {"skill": "<existing_skill>", "args": {...}}, ... ],
  "success_predicate": {"kind": "dlvl_increase" | "dlvl_at_least" | "inventory_grew" | "level_explored", "n": <int, only for dlvl_at_least>}
}

Pick objectives that build on already-learned skills and the current depth.
Keep macros short (1-4 steps). Never invent skill names. JSON only."""


class GLMProposer:
    """GLM-backed proposer (`z-ai/glm-5` via Prime Inference).

    Mirrors refiner.TeacherLLMRefiner's credential resolution exactly:
        REFINER_BASE_URL   (OpenAI-compatible Prime Inference endpoint)
        REFINER_API_KEY     (falls back to ANTHROPIC_API_KEY)
        REFINER_TIMEOUT_S   (default 30)

    WIRED but intentionally NOT called in the smoke (keeps API/LLM cost zero).
    Select it with `--proposer glm` once credentials + budget are available.
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
        self.api_key = (
            api_key
            or os.getenv("REFINER_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        self.timeout_s = float(os.getenv("REFINER_TIMEOUT_S", timeout_s))
        if not self.api_key:
            raise RuntimeError(
                "GLMProposer requires an API key in REFINER_API_KEY / ANTHROPIC_API_KEY. "
                "Use --proposer stub for a keyless, zero-cost run."
            )

    def _skill_catalog(self) -> str:
        schemas = registry.all_schemas()
        lines = []
        for name in sorted(schemas):
            desc = (schemas[name].get("description") or "").strip().replace("\n", " ")
            params = schemas[name].get("parameters", {}) or {}
            arg_names = ", ".join(params.keys()) or "(none)"
            lines.append(f"- {name}(args: {arg_names}): {desc[:160]}")
        return "\n".join(lines)

    def propose(self, summary: StateSummary) -> Objective:
        from openai import OpenAI  # lazy: keeps module import network-free

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        system = _GLM_SYSTEM_PROMPT % {"skills": self._skill_catalog()}
        user = (
            "=== Agent state summary ===\n"
            + json.dumps(summary.to_dict(), indent=2)
            + "\n\nPropose the next objective + macro as JSON."
        )
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            timeout=self.timeout_s,
        )
        raw = resp.choices[0].message.content or ""
        return _parse_objective(raw)


def _parse_objective(raw: str) -> Objective:
    """Parse a GLM JSON proposal into an Objective, validating skill names.

    Permissive: falls back to a safe descend objective if the model output is
    unusable, so the loop never crashes on a bad proposal (refiner._parse_edits
    pattern)."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data: dict = {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        import re

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = {}
    if not isinstance(data, dict):
        data = {}

    valid = _valid_skills()
    steps: list[MacroStep] = []
    for s in data.get("macro") or []:
        if not isinstance(s, dict):
            continue
        sk = s.get("skill")
        if not isinstance(sk, str) or (valid and sk not in valid):
            continue
        args = s.get("args") if isinstance(s.get("args"), dict) else {}
        steps.append(MacroStep(skill=sk, args=args))

    pred = data.get("success_predicate")
    if not isinstance(pred, dict) or pred.get("kind") not in (
        "dlvl_increase",
        "dlvl_at_least",
        "inventory_grew",
        "level_explored",
    ):
        pred = {"kind": "dlvl_increase"}

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = "glm_macro"
    desc = data.get("objective")
    if not isinstance(desc, str) or not desc.strip():
        desc = "descend one level"

    if not steps:
        # Unusable macro — fall back to the canonical descend macro so the
        # round still does something rather than crashing.
        steps = [
            MacroStep(skill="explore_and_descend", args={"max_floors": 1, "max_game_steps": 600})
        ]
        pred = {"kind": "dlvl_increase"}

    return Objective(
        name=name.strip(),
        description=desc.strip(),
        macro=steps,
        success_predicate=pred,
    )


def make_proposer(kind: str) -> Proposer:
    if kind == "stub":
        return StubProposer()
    if kind == "glm":
        return GLMProposer()
    raise ValueError(f"Unknown proposer {kind!r}; use 'stub' or 'glm'.")


# --------------------------------------------------------------------------
# Execution + verification
# --------------------------------------------------------------------------


@dataclass
class ExecResult:
    success: bool
    before_dlvl: int
    after_dlvl: int
    inv_before: int
    inv_after: int
    terminated: bool
    feedback: list[str]


def _read_dlvl(obs) -> int:
    """Dungeon level (depth) from raw blstats (BLSTATS_IDX['depth'] == 12)."""
    try:
        return int(obs.blstats[12])
    except Exception:
        return 1


def execute_macro(
    env: NetHackCoreEnv,
    structured_obs,
    character: dict,
    objective: Objective,
) -> ExecResult:
    """Run the macro one step at a time, re-observing after each step.

    Closed-loop skills (e.g. explore_and_descend) set `pre_executed=True` and have
    already stepped the env; we adopt their `final_obs`. Open-loop skills return a
    list of NLE actions we step through here.
    """
    raw_before = env.last_observation
    before_dlvl = _read_dlvl(_RawView(env))
    inv_before = len(structured_obs.inventory or [])
    feedback: list[str] = []
    terminated = False
    cur_struct = structured_obs

    for step in objective.macro:
        result = registry.call(step.skill, env, cur_struct, **dict(step.args))
        feedback.append(f"{step.skill}: {result.feedback}")
        if result.pre_executed:
            # Skill already stepped the env; adopt its final obs.
            if result.final_obs is not None:
                cur_struct = shape_observation(result.final_obs, character)
            terminated = terminated or result.pre_terminated or result.pre_truncated
        else:
            for action in result.actions:
                obs, _r, term, trunc, _info = env.step(int(action))
                cur_struct = shape_observation(obs, character)
                if term or trunc:
                    terminated = True
                    break
        if terminated:
            break

    after_dlvl = _read_dlvl(_RawView(env))
    inv_after = len(cur_struct.inventory or [])
    success = _check_success(
        objective.success_predicate,
        before_dlvl=before_dlvl,
        after_dlvl=after_dlvl,
        inv_before=inv_before,
        inv_after=inv_after,
        macro_errored=any("Unknown skill" in f or "call failed" in f for f in feedback),
    )
    return ExecResult(
        success=success,
        before_dlvl=before_dlvl,
        after_dlvl=after_dlvl,
        inv_before=inv_before,
        inv_after=inv_after,
        terminated=terminated,
        feedback=feedback,
    )


class _RawView:
    """Tiny adapter exposing `.blstats` off the env's last raw observation, so
    `_read_dlvl` can read depth without re-shaping a full StructuredObservation."""

    def __init__(self, env: NetHackCoreEnv) -> None:
        keys = env.observation_keys
        last = env.last_observation
        self.blstats = last[keys.index("blstats")] if last is not None else None


def _check_success(
    predicate: dict,
    *,
    before_dlvl: int,
    after_dlvl: int,
    inv_before: int,
    inv_after: int,
    macro_errored: bool,
) -> bool:
    """Evaluate an objective's success predicate. Unknown kinds fail closed."""
    kind = predicate.get("kind")
    if kind == "dlvl_increase":
        return after_dlvl > before_dlvl
    if kind == "dlvl_at_least":
        try:
            return after_dlvl >= int(predicate.get("n", 1))
        except (TypeError, ValueError):
            return False
    if kind == "inventory_grew":
        return inv_after > inv_before
    if kind == "level_explored":
        # Best-effort: success if the macro ran without a hard tool error.
        return not macro_errored
    return False


# --------------------------------------------------------------------------
# Skill library (persistent; refiner-compatible format)
# --------------------------------------------------------------------------


class SkillLibrary:
    """Persistent name -> list[MacroStep] library.

    Serialized in the SAME shape `refiner.snapshot_components()` writes for its
    `skills` field: a dict `name -> [{"skill", "args"}, ...]`. That makes the
    saved JSON a drop-in `bootstrap_dir` skills blob loadable by
    `refiner.load_components`.
    """

    def __init__(self) -> None:
        self._skills: dict[str, list[MacroStep]] = {}

    def __len__(self) -> int:
        return len(self._skills)

    def names(self) -> list[str]:
        return sorted(self._skills)

    def add(self, name: str, macro: list[MacroStep]) -> None:
        self._skills[name] = list(macro)

    def to_components_skills(self) -> dict:
        """The refiner `skills` component shape."""
        return {
            name: [{"skill": s.skill, "args": s.args} for s in steps]
            for name, steps in self._skills.items()
        }

    @classmethod
    def from_components_skills(cls, data: dict) -> "SkillLibrary":
        lib = cls()
        for name, steps in (data or {}).items():
            if not isinstance(steps, list):
                continue
            macro = [
                MacroStep(skill=s["skill"], args=s.get("args", {}))
                for s in steps
                if isinstance(s, dict) and isinstance(s.get("skill"), str)
            ]
            if macro:
                lib._skills[name] = macro
        return lib

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_components_skills(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "SkillLibrary":
        if not path.exists():
            return cls()
        try:
            return cls.from_components_skills(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return cls()


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _summarize(env: NetHackCoreEnv, structured_obs, library: SkillLibrary,
               max_dlvl: int, failures: list[str]) -> StateSummary:
    status = structured_obs.status or {}
    return StateSummary(
        dlvl=int(status.get("depth", 1) or 1),
        max_dlvl=max_dlvl,
        hp=int(status.get("hitpoints", 0) or 0),
        hp_max=int(status.get("max_hitpoints", 0) or 0),
        inventory_count=len(structured_obs.inventory or []),
        learned_skills=library.names(),
        recent_failures=list(failures),
    )


def run(iterations: int, seed: int, proposer_kind: str, out_root: Path) -> dict:
    proposer = make_proposer(proposer_kind)

    out_dir = out_root / f"voyager_seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "voyager_trace.ndjson"
    library_path = out_dir / "skill_library.json"

    # Carry the library across episodes: load any existing one (bootstrap_dir
    # semantics), then grow it.
    library = SkillLibrary.load(library_path)

    env = NetHackCoreEnv()
    env.seed(core=seed, disp=seed)
    obs, _meta = env.reset()
    character = bootstrap_character(env)
    structured_obs = shape_observation(obs, character)

    max_dlvl = _read_dlvl(obs)
    failures: list[str] = []
    successes = 0

    with trace_path.open("w") as trace_f:
        for it in range(iterations):
            summary = _summarize(env, structured_obs, library, max_dlvl, failures)
            objective = proposer.propose(summary)

            exec_result = execute_macro(env, structured_obs, character, objective)
            # Refresh structured_obs from the env's latest raw observation.
            structured_obs = shape_observation(env._last_observation, character)
            max_dlvl = max(max_dlvl, exec_result.after_dlvl)

            stored = False
            if exec_result.success:
                library.add(objective.name, objective.macro)
                successes += 1
                stored = True
            else:
                failures.append(
                    f"{objective.name}: {objective.description} (predicate "
                    f"{objective.success_predicate.get('kind')} not met)"
                )

            record = {
                "iteration": it,
                "objective": objective.description,
                "skill_name": objective.name,
                "macro": [{"skill": s.skill, "args": s.args} for s in objective.macro],
                "success_predicate": objective.success_predicate,
                "success": exec_result.success,
                "stored": stored,
                "before_dlvl": exec_result.before_dlvl,
                "after_dlvl": exec_result.after_dlvl,
                "dlvl": exec_result.after_dlvl,
                "max_dlvl": max_dlvl,
                "terminated": exec_result.terminated,
                "library_size": len(library),
                "feedback": exec_result.feedback,
            }
            trace_f.write(json.dumps(record) + "\n")
            trace_f.flush()
            log.info(
                "iter %d: %-22s pred=%-14s success=%s dlvl %d->%d lib=%d",
                it, objective.name, objective.success_predicate.get("kind"),
                exec_result.success, exec_result.before_dlvl,
                exec_result.after_dlvl, len(library),
            )

            if exec_result.terminated:
                log.info("episode terminated (died / level-end) at iter %d", it)
                break

    library.save(library_path)
    env.close()

    return {
        "iterations_run": min(iterations, it + 1),
        "successes": successes,
        "library_size": len(library),
        "library_names": library.names(),
        "max_dlvl": max_dlvl,
        "trace_path": str(trace_path),
        "library_path": str(library_path),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Voyager driver for NetHack.")
    parser.add_argument("--iterations", type=int, default=6)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--proposer", choices=["stub", "glm"], default="stub")
    parser.add_argument(
        "--out-root",
        type=str,
        default="environments/nethack/outputs/web_play",
        help="Directory under which voyager_seed<seed>/ is written.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    t0 = time.time()
    summary = run(
        iterations=args.iterations,
        seed=args.seed,
        proposer_kind=args.proposer,
        out_root=Path(args.out_root),
    )
    summary["elapsed_s"] = round(time.time() - t0, 1)

    print("\n=== Voyager run summary ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
