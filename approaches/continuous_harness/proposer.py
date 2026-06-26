"""Proposers: given prior-iteration results, return the next HarnessConfig.

Two implementations:

  FallbackProposer  deterministic, no API. Cycles a small candidate list
                    (vary `variant`, toggle a fixed prompt_addendum). Used by
                    --dry-run and as the safety net when the LLM proposer fails.

  LLMProposer       calls GLM-5 via the OpenAI-compatible Prime Inference
                    endpoint (same creds as the refiner). Given a compact
                    summary of prior iterations it returns STRICT JSON, which we
                    parse + validate into a HarnessConfig constrained to the
                    allowed variant/skill_set sets.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Optional, Protocol

from .config import ALLOWED_SKILL_SETS, ALLOWED_VARIANTS, HarnessConfig


class Proposer(Protocol):
    """Returns the next config given the base config and prior iteration records.

    `history` is a list of dicts shaped like:
        {"config": {...summary...}, "depth": float, "reward": float | None,
         "excerpt": str}
    """

    def propose(
        self, base: HarnessConfig, history: list[dict[str, Any]]
    ) -> HarnessConfig: ...


# ---------------------------------------------------------------------------- #
# Fallback (deterministic, no API)
# ---------------------------------------------------------------------------- #

# A short ladder of obs-format candidates the fallback cycles through. Picked to
# be cheap, allowed, and meaningfully different (ASCII baseline, descent-salient,
# structured map, natural-language scene).
_FALLBACK_VARIANTS = ("B1", "FD", "JSON", "B")

_FALLBACK_ADDENDUM = (
    "DEPTH FOCUS: your single most important objective is to descend the "
    "dungeon. Prefer stairs-down, search for hidden passages when stuck, and "
    "avoid burning turns exploring fully-cleared levels."
)


class FallbackProposer:
    """Deterministic proposer. Each call advances one step along a fixed ladder:
    it rotates `variant` through `_FALLBACK_VARIANTS` and toggles a fixed
    `prompt_addendum` on/off, so successive iterations are always distinct and
    fully reproducible with no network access."""

    def propose(
        self, base: HarnessConfig, history: list[dict[str, Any]]
    ) -> HarnessConfig:
        step = len(history)  # 0 on the first *proposed* config (after base)
        variant = _FALLBACK_VARIANTS[step % len(_FALLBACK_VARIANTS)]
        addendum = _FALLBACK_ADDENDUM if (step % 2 == 0) else None
        return dataclasses.replace(
            base, variant=variant, prompt_addendum=addendum,
        ).validate()


# ---------------------------------------------------------------------------- #
# LLM proposer (GLM-5 via Prime Inference, OpenAI-compatible)
# ---------------------------------------------------------------------------- #

_PROPOSER_SYSTEM_PROMPT = (
    "You are tuning the HARNESS around an immutable NetHack game engine. You may "
    "ONLY change three surfaces: the observation format (`variant`), the tool "
    "surface (`skill_set`), and a free-text system-prompt addendum plus optional "
    "named macros and sub-agents. You CANNOT change the game. Your goal is to "
    "maximize the mean curriculum depth (curriculum_floor 1..6) of the policy "
    "agent.\n\n"
    "HARD CONSTRAINT — this is a PRIMITIVES-ONLY curriculum: the agent must "
    "NAVIGATE to real staircases itself. The `descend`, `ascend`, "
    "`find_and_descend`, and `explore_and_descend` skills are FORBIDDEN — never "
    "put them in `skill_set` and never reference them. Do NOT use the named "
    "skill_sets 'full' or 'netplay' (they contain descend/ascend); use a "
    "comma-separated allowlist instead. The only way to take stairs is the raw "
    "`press_down`/`press_up` keys, which work ONLY when the agent is standing on "
    "a '>'/'<' tile. So the agent must read the map, route to the stairs "
    "(move/move_to/autoexplore/search), step onto them, then press_down.\n\n"
    "The score axis: curriculum_floor goes 1->2->3 in Dungeons of Doom, then a "
    "real '>' on DoD level 3 jumps to the deep segment (floor 4=Gehennom) with a "
    "stat upgrade, then 5,6 going deeper. Reaching floor 4 (the deep segment) is "
    "the key milestone — it requires navigating 3 levels of stairs. Use the "
    "prompt_addendum, macros, and observation format to make stair-finding and "
    "routing easier. Pick a `variant` that renders the ASCII map clearly so the "
    "agent can see the stairs. Respond with STRICT JSON only."
)


def _resolve_creds(model: str) -> dict[str, Optional[str]]:
    """Resolve {model, base_url, api_key} from the refiner env vars, mirroring
    `nethack_harness.refiner._resolve_*`. Prefers REFINER_* (teacher creds) and
    falls back to PI_API_KEY (the Prime Inference policy key)."""
    api_key = (
        os.getenv("REFINER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("PI_API_KEY")
    )
    base_url = os.getenv("REFINER_BASE_URL")
    return {"model": model, "base_url": base_url, "api_key": api_key}


def _build_user_msg(base: HarnessConfig, history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("ALLOWED variant values: " + ", ".join(ALLOWED_VARIANTS))
    lines.append(
        "ALLOWED skill_set values: " + ", ".join(ALLOWED_SKILL_SETS)
        + " (or a comma-separated allowlist of skill names)."
    )
    lines.append("")
    lines.append("Base/fixed run params (DO NOT change these):")
    lines.append(json.dumps({
        "tier": base.tier,
        "policy_model": base.policy_model,
        "teacher_model": base.teacher_model,
        "max_turns": base.max_turns,
        "refine_interval": base.refine_interval,
        "seed": base.seed,
        "n_seeds": base.n_seeds,
    }, indent=2))
    lines.append("")
    if history:
        lines.append("PRIOR ITERATIONS (config -> achieved depth):")
        for i, rec in enumerate(history):
            lines.append(json.dumps({
                "iteration": i,
                "config": rec.get("config"),
                "depth": rec.get("depth"),
                "reward": rec.get("reward"),
                "excerpt": (rec.get("excerpt") or "")[:600],
            }, indent=2))
    else:
        lines.append("No prior iterations yet; propose a strong first variation.")
    lines.append("")
    lines.append(
        "Return STRICT JSON with EXACTLY these keys: "
        '{"variant": <str>, "skill_set": <str>, "prompt_addendum": <str>, '
        '"macros": {<name>: [<action-strings>]}, '
        '"subagents": {<name>: {<fields>}}, "objective": <str|null>}. '
        "Use {} for empty macros/subagents."
    )
    return "\n".join(lines)


class LLMProposer:
    """Calls GLM-5 (default) through the OpenAI-compatible Prime Inference
    endpoint. Reuses the refiner's client pattern (OpenAI client +
    response_format=json_object). On ANY failure it falls back to
    FallbackProposer so the loop never stalls."""

    def __init__(
        self,
        model: str = "z-ai/glm-5",
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url or os.getenv("REFINER_BASE_URL")
        self.api_key = (
            api_key
            or os.getenv("REFINER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("PI_API_KEY")
        )
        self.timeout_s = float(os.getenv("REFINER_TIMEOUT_S", timeout_s))
        self._fallback = FallbackProposer()

    def _call_chat(self, user_msg: str) -> str:
        from openai import OpenAI  # lazy import, mirrors refiner

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _PROPOSER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            # GLM is a REASONING model: without a generous max_tokens it spends
            # the whole budget on hidden reasoning and returns EMPTY content,
            # which then fails json.loads and silently drops to the fallback
            # proposer. Give it room to emit the JSON after reasoning.
            max_tokens=8000,
            timeout=self.timeout_s,
        )
        return resp.choices[0].message.content or ""

    def propose(
        self, base: HarnessConfig, history: list[dict[str, Any]]
    ) -> HarnessConfig:
        if not self.api_key:
            # No creds -> deterministic fallback (keeps the loop runnable).
            return self._fallback.propose(base, history)
        try:
            raw = self._call_chat(_build_user_msg(base, history))
            data = json.loads(raw)
        except Exception:
            return self._fallback.propose(base, history)
        return self._config_from_json(base, data)

    @staticmethod
    def _config_from_json(base: HarnessConfig, data: dict[str, Any]) -> HarnessConfig:
        if not isinstance(data, dict):
            return FallbackProposer().propose(base, [])
        variant = data.get("variant")
        skill_set = data.get("skill_set")
        addendum = data.get("prompt_addendum")
        macros = data.get("macros")
        subagents = data.get("subagents")
        objective = data.get("objective")
        cfg = dataclasses.replace(
            base,
            variant=variant if isinstance(variant, str) else base.variant,
            skill_set=skill_set if isinstance(skill_set, str) else base.skill_set,
            prompt_addendum=addendum if isinstance(addendum, str) else None,
            macros=macros if isinstance(macros, dict) else None,
            subagents=subagents if isinstance(subagents, dict) else None,
            objective=objective if isinstance(objective, str) else None,
        )
        # `.validate()` clamps variant/skill_set into the allowed sets.
        return cfg.validate()
