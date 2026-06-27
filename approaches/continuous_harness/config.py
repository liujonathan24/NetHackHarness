"""HarnessConfig: a single point in the harness configuration space.

The loop mutates THREE surfaces between iterations, all of which map onto
existing `load_environment(...)` kwargs + bootstrap files — the game engine is
never touched:

  - observation format  -> `variant`     (one of ALLOWED_VARIANTS)
  - tools / skills       -> `skill_set`   (one of ALLOWED_SKILL_SETS, or a
                                            comma-separated allowlist)
  - prompt + macros + sub-agents + journal -> a `seed<N>.json` bootstrap file
                                            written into `bootstrap_dir`, loaded
                                            by `variant="CH"` at rollout start.

`to_bootstrap_json(seed)` emits exactly the dict shape produced by
`nethack_harness.refiner.snapshot_components(state)`:

    {
      "prompt_addendum": str,
      "subagents": {name: {<dict>}},
      "skills":    {name: [<list>]},     # macros == named skill/action lists
      "notes":     {key: str},
      "objective": str | None,
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Optional

# Allowed observation-format variants (keys of VARIANT_REGISTRY). Kept as a
# literal mirror so config validation never has to import the env (which pulls
# in heavy deps). The loop validates against this set before launching evals.
ALLOWED_VARIANTS = (
    "B1", "B0", "N", "B", "G", "R", "ND", "FD",
    "E1", "E2", "IMG", "IMG_TTY", "JSON", "TOON", "P", "CH",
)

# Allowed named skill_sets. A comma-separated allowlist (e.g. "move,descend")
# is also accepted and validated loosely (non-empty tokens).
ALLOWED_SKILL_SETS = ("full", "move", "dir8", "netplay")


@dataclass
class HarnessConfig:
    """One harness configuration + the fixed run parameters used to eval it.

    The three MUTABLE surfaces:
        variant          obs format (string in ALLOWED_VARIANTS)
        skill_set        tool surface (ALLOWED_SKILL_SETS or "a,b,c" allowlist)
        prompt_addendum  system-prompt addendum injected via bootstrap
        macros           {name: [actions...]} named skill/action lists
        subagents        {name: {...}} sub-agent definitions

    Fixed run params (not mutated by the proposer; carried for reproducibility):
        tier, policy_model, teacher_model, max_turns, refine_interval,
        seed, n_seeds.
    """

    # --- mutable surfaces ---
    # Always the uncompressed JSON map — never B1/compressed. The obs format is
    # NOT something we optimize: a readable structured map is a hard requirement.
    variant: str = "JSON"
    skill_set: str = "full"
    prompt_addendum: Optional[str] = None
    macros: Optional[dict] = None
    subagents: Optional[dict] = None

    # --- fixed run params ---
    tier: str = "corridor_explore"
    policy_model: str = "z-ai/glm-4.6"
    teacher_model: str = "z-ai/glm-5"
    max_turns: int = 200
    refine_interval: int = 20
    seed: int = 0
    n_seeds: int = 1

    # --- bookkeeping ---
    notes: dict = field(default_factory=dict)
    objective: Optional[str] = None

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    def validate(self) -> "HarnessConfig":
        """Clamp the mutable surfaces into the allowed sets. Returns a (possibly
        new) valid config; never raises so a bad LLM proposal can't crash the
        loop — it just falls back to defaults for the offending field."""
        variant = self.variant if self.variant in ALLOWED_VARIANTS else "B1"
        skill_set = self.skill_set
        if skill_set not in ALLOWED_SKILL_SETS:
            if "," in (skill_set or ""):
                toks = [t.strip() for t in skill_set.split(",") if t.strip()]
                skill_set = ",".join(toks) if toks else "full"
            else:
                skill_set = "full"
        if self.policy_model and self.teacher_model and \
                self.policy_model == self.teacher_model:
            # Policy and teacher MUST differ (Prime Inference serves both).
            raise ValueError(
                f"policy_model and teacher_model must differ; both are "
                f"{self.policy_model!r}."
            )
        macros = self.macros if isinstance(self.macros, dict) else None
        subagents = self.subagents if isinstance(self.subagents, dict) else None
        return replace(
            self, variant=variant, skill_set=skill_set,
            macros=macros, subagents=subagents,
        )

    # ------------------------------------------------------------------ #
    # bootstrap emission
    # ------------------------------------------------------------------ #
    def to_bootstrap_dict(self, seed: int) -> dict[str, Any]:
        """Return the dict matching `refiner.snapshot_components(state)`.

        Macros are stored under `skills` (value MUST be a list — `load_components`
        keeps only list-valued entries). Sub-agents under `subagents` (value MUST
        be a dict). The `seed` arg is accepted for symmetry / future per-seed
        bootstraps; the current shape is seed-independent.
        """
        skills: dict[str, list] = {}
        for name, body in (self.macros or {}).items():
            if isinstance(body, list):
                skills[str(name)] = body
            elif isinstance(body, str):
                # Allow a bare action string -> single-element list.
                skills[str(name)] = [body]

        subagents: dict[str, dict] = {}
        for name, body in (self.subagents or {}).items():
            if isinstance(body, dict):
                subagents[str(name)] = body

        return {
            "prompt_addendum": self.prompt_addendum or "",
            "subagents": subagents,
            "skills": skills,
            "notes": dict(self.notes or {}),
            "objective": self.objective,
        }

    def to_bootstrap_json(self, seed: int) -> str:
        """Serialize `to_bootstrap_dict` to a JSON string (the seed<N>.json body)."""
        return json.dumps(self.to_bootstrap_dict(seed), indent=2, sort_keys=True)

    # ------------------------------------------------------------------ #
    # eval-arg emission
    # ------------------------------------------------------------------ #
    def to_env_args(self, bootstrap_dir: str, trace_dir: str) -> dict[str, Any]:
        """Build the `-a` JSON payload for `vf-eval nethack`. Always passes
        `variant="CH"` semantics through `bootstrap_dir` only when a bootstrap is
        meaningful: CH consumes the bootstrap, other variants ignore it (the env
        guards bootstrap I/O behind `variant == "CH"`), so we always pass it and
        let the env decide."""
        # Pin the per-rollout seeds to seed..seed+n_seeds-1 so (a) the eval is
        # deterministic across iterations and (b) each rollout's seed matches a
        # `seed<N>.json` bootstrap file. Without explicit_seeds the env draws
        # RANDOM episode seeds that never match the written bootstrap filenames,
        # silently disabling CH prompt/macro evolution.
        explicit_seeds = list(range(self.seed, self.seed + max(1, self.n_seeds)))
        return {
            "variant": self.variant,
            "skill_set": self.skill_set,
            "refiner_model": self.teacher_model,
            "tier": self.tier,
            "max_turns": self.max_turns,
            "refine_interval": self.refine_interval,
            "seed": self.seed,
            "explicit_seeds": explicit_seeds,
            "bootstrap_dir": bootstrap_dir,
            "trace_dir": trace_dir,
        }

    def summary(self) -> dict[str, Any]:
        """Compact, JSON-safe summary for the run-log / proposer context."""
        return {
            "variant": self.variant,
            "skill_set": self.skill_set,
            "prompt_addendum": (self.prompt_addendum or "")[:400],
            "macros": list((self.macros or {}).keys()),
            "subagents": list((self.subagents or {}).keys()),
            "tier": self.tier,
            "policy_model": self.policy_model,
            "teacher_model": self.teacher_model,
            "max_turns": self.max_turns,
            "refine_interval": self.refine_interval,
            "seed": self.seed,
            "n_seeds": self.n_seeds,
        }
