"""
nethack
=======

The Prime Intellect Environments Hub wrapper for the NetHack training env.

This is layer 2: a thin shim that consumes `nethack_core` and presents it as a
verifiers MultiTurnEnv with chat-shaped tool calling and a composable rubric.

Published as `primeintellect/nethack` (TBD with Alex).
"""

from __future__ import annotations

import random
import re
from typing import Any, Optional

import verifiers as vf
from datasets import Dataset

from nethack_core.env import NetHackCoreEnv
from nethack_core.journal import Journal
from nethack_core.observations import shape as shape_observation
from nethack_core.skills import registry as skill_registry, list_skills
from nethack_core.curriculum import get_tier, list_tiers, TierName


# ---------- verifiers 0.1.14 compat shim ----------
#
# verifiers 0.1.14's v1.utils.sandbox_program_utils.message_from_response
# assumes every tool_call has the OpenAI SDK nested shape (.function.name /
# .function.arguments). Some endpoints (e.g. api.pinference.ai for Qwen) and
# verifiers' own ToolCall dataclass use the flat shape (.name / .arguments).
# Without this shim, vf-eval raises:
#   AttributeError("'ToolCall' object has no attribute 'function'")
# Remove once the upstream PR lands.
def _patch_verifiers_message_from_response() -> None:
    try:
        from verifiers.v1.utils import sandbox_program_utils as _spu
    except ImportError:
        return
    if not hasattr(_spu, "message_from_response"):
        return  # different verifiers build — nothing to patch

    def _safe(response):  # type: ignore[no-redef]
        choice = response.choices[0]
        message = choice.message
        data = {"role": getattr(message, "role", "assistant")}
        content = getattr(message, "content", None)
        if content is not None:
            data["content"] = content
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            packed = []
            for call in tool_calls:
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", None) if fn is not None else getattr(call, "name", None)
                args = getattr(fn, "arguments", None) if fn is not None else getattr(call, "arguments", None)
                packed.append({
                    "id": getattr(call, "id", None),
                    "type": getattr(call, "type", "function"),
                    "function": {"name": name, "arguments": args},
                })
            data["tool_calls"] = packed
        return data

    _spu.message_from_response = _safe


_patch_verifiers_message_from_response()


# ---------- system prompt ----------

SYSTEM_PROMPT = """You are playing NetHack, a procedurally-generated dungeon-crawling roguelike.

Each turn shows: map (ASCII, runs `.{20}` = 20 dots), stats, inventory
(skipped on "unchanged"), messages, any menu. Act by calling one tool.

=== STRATEGY PRIMER ===
GLYPH KEY:
Terrain: `>` stairs DOWN, `<` stairs UP (NOT down), `_` altar, `{` fountain,
`}` pool, `#` corridor, `.` floor, `|`/`-` walls, `+` door, `\\` throne,
`$` gold, `%` food/corpse, `[`/`)`/`(`/`*`/`?` items. Creatures are LETTERS
(a-z, A-Z): `d` canine, `f` feline/lichen, `r` rat, `x` grid bug, `B` bat,
`k` kobold, `o` orc, `@` humans (and YOU). No "fireplace" glyph — adjacent
`f` is a creature. `@` hides the tile under you — read UNDER PLAYER.

VISIBLE FEATURES lists every stairs/altar/fountain on the visible map
with (x,y). If `stairs DOWN` isn't listed, no `>` is visible — don't
pattern-match the grid; explore or `search`. To descend: (1) find `>`,
(2) walk ON it, (3) call `descend`. If descend fails, recheck UNDER PLAYER.

Pitfalls: `eat`/`quaff`/`read` need an `item` arg. At HP <30% retreat or
`search` to rest. `engrave_elbereth` when cornered (Elbereth scares most
monsters). Menus auto-dismiss; never call menu/inventory tools.

=== SKILLS CHEAT SHEET ===
- Traverse a level: `autoexplore`
- Reach a known tile: `move_to(x, y)`
- Step: `move(direction=N|NE|E|...)`
- Pickup: `pickup`; Descend: `descend` (must be on `>`)
- Notes: `add_note` / `recall(query=...)` / `pin_objective`
- Search/rest: `search(times=10)` for hidden doors, `search(times=20)` to heal
- Wiki: `wiki_lookup(page="kobold")` / `wiki_search(query="cockatrice")`
- Combat: `attack(direction=N|...)` — never on `[PET — don't attack]`

Your top-level goal is pre-pinned as `Objective:` in JOURNAL."""


# ---------- observation formatting for chat ----------
#
# Per-turn observation cost is the dominant line item in our token bill
# (~27k tok/turn at v0.0.15, ~4M tok per 150-turn rollout). Three cheap
# token-savers per docs/PROMPTING_SURVEY.md, with state-tracking so we don't
# re-send static content:
#
#   1. Strip blank tty rows from the map view.
#   2. Glyph-run encode long runs of `.` and `#` in the map view.
#   3. Inventory diff-only: emit "(unchanged)" when the inventory letter set
#      hasn't changed since last render (only meaningful if `state` is
#      threaded through; the helper still works with state=None).
#
# Combined target: ~30-40% token reduction on map-heavy turns.
# Toggle off by passing compact=False (e.g. for debugging / replay viewer).


def _strip_blank_rows(map_view: str) -> str:
    """Drop fully-blank rows; trim trailing whitespace per row."""
    out = []
    for row in map_view.splitlines():
        r = row.rstrip()
        if r:
            out.append(r)
    return "\n".join(out)


def _glyph_run_encode(map_view: str, min_run: int = 5) -> str:
    """Replace runs of `.` (floor) or `#` (corridor) of length >= min_run
    with `<ch>{N}`. Lossless; reversible. Saves ~15-25% on dungeon-row
    length once corridors are visible.
    """
    import re
    def _sub(m):
        ch = m.group(0)[0]
        return f"{ch}{{{len(m.group(0))}}}"
    pattern = re.compile(r"\.{" + str(min_run) + r",}|#{" + str(min_run) + r",}")
    return "\n".join(pattern.sub(_sub, row) for row in map_view.splitlines())


def _inventory_fingerprint(inventory) -> tuple:
    """Cheap hashable signature so we can diff inventories across turns."""
    return tuple((it.letter, it.description) for it in inventory)


def _run_length_encode_messages(messages) -> list:
    """Collapse consecutive identical messages into `text (xN)`. Saves tokens
    on combat spam ("You hit the kobold. You hit the kobold. ..."). Order-
    preserving; only consecutive duplicates collapse.
    """
    if not messages:
        return []
    out = []
    last = None
    run = 0
    for m in messages:
        if m == last:
            run += 1
        else:
            if last is not None:
                out.append(f"{last} (x{run})" if run > 1 else last)
            last = m
            run = 1
    if last is not None:
        out.append(f"{last} (x{run})" if run > 1 else last)
    return out


def format_observation_as_chat(
    structured,
    journal: Optional[Journal] = None,
    state: Optional[dict] = None,
    compact: bool = True,
    journal_max_chars: int = 2000,
) -> str:
    """Render a StructuredObservation as a text block for the user message.

    When `state` is threaded through, we deduplicate static content
    across turns. `compact=False` disables all token-savers (used by tests
    and the replay viewer to inspect raw content).
    """
    lines: list[str] = []
    if journal is not None and not journal.is_empty():
        # Diff-only journal: when state is threaded through and the journal
        # hasn't changed since last render, emit "(unchanged)" instead of the
        # full block. Saves ~journal_max_chars/turn on stretches with no
        # journal writes. Belief-state ticks every 25 turns will refresh.
        cur_keys = tuple(sorted(journal.notes.keys()))
        cur_fp = (journal.objective, cur_keys)
        prev_fp = state.get("_journal_fingerprint") if state is not None else None
        lines.append("=== JOURNAL ===")
        if compact and prev_fp == cur_fp:
            # Diff-only: omit notes, but ALWAYS surface the pinned objective.
            # After history compaction strips turn 1, the agent has no way to
            # recall its goal from context — and the 9071d001 trace showed
            # zero `recall` calls, so the model wasn't retrieving it either.
            if journal.objective:
                lines.append(f"Objective: {journal.objective}")
                lines.append("(notes unchanged since last turn)")
            else:
                lines.append("(unchanged since last turn)")
        else:
            lines.append(journal.render(max_chars=journal_max_chars))
        if state is not None:
            state["_journal_fingerprint"] = cur_fp
        lines.append("")
    lines.append("=== MAP ===")
    map_view = structured.map_view
    if compact:
        map_view = _strip_blank_rows(map_view)
        map_view = _glyph_run_encode(map_view)
    lines.append(map_view)
    lines.append("")
    lines.append("=== STATUS ===")
    s = structured.status
    # Include max-dlvl-reached when state is threaded so the model can see
    # progression at a glance (e.g. on a return-to-prev-level via stairs up).
    max_dlvl = state.get("max_dlvl_reached") if state else None
    dlvl_part = f"Dlvl: {s.get('depth', '?')}"
    if max_dlvl is not None and max_dlvl > s.get("depth", 0):
        dlvl_part = f"Dlvl: {s.get('depth', '?')} (max reached: {max_dlvl})"
    pos_part = ""
    if "x" in s and "y" in s:
        pos_part = f"  Pos: ({s['x']},{s['y']})"
    lines.append(f"HP: {s.get('hitpoints', '?')}/{s.get('max_hitpoints', '?')}  "
                 f"AC: {s.get('armor_class', '?')}  "
                 f"{dlvl_part}  "
                 f"Turn: {s.get('time', '?')}  "
                 f"XP: {s.get('experience_level', '?')}  "
                 f"$: {s.get('gold', 0)}{pos_part}")
    c = structured.character
    if c:
        lines.append(f"Character: {c.get('role', '?')} ({c.get('race', '?')}, {c.get('alignment', '?')})")
    lines.append("")
    if structured.inventory:
        prev_fp = state.get("_inv_fingerprint") if state is not None else None
        cur_fp = _inventory_fingerprint(structured.inventory)
        if compact and prev_fp == cur_fp:
            lines.append("=== INVENTORY (unchanged) ===")
        else:
            lines.append("=== INVENTORY ===")
            for item in structured.inventory:
                lines.append(f"  {item.letter}: {item.description}")
        if state is not None:
            state["_inv_fingerprint"] = cur_fp
        lines.append("")
    # UNDER PLAYER: critically tells the agent what tile @ is hiding.
    # Especially important for stairs (`>` down vs `<` up).
    under = getattr(structured, "under_player", None)
    if under:
        lines.append(f"=== UNDER PLAYER === {under}")
        lines.append("")
    adj = getattr(structured, "adjacent", None) or {}
    if adj:
        # Cheap "what's around me" block; saves the model from parsing the
        # map for adjacent tiles. Always emitted (even compact=False) — it's
        # a strictly additive signal worth ~30 tokens.
        order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        adj_line = " ".join(f"{d}={adj.get(d, '?')}" for d in order)
        lines.append(f"=== ADJACENT === {adj_line}")
        lines.append("")
    # NEXT-ACTION HINT: the model kept missing the moment to descend or
    # attack adjacent hostiles. If on stairs down, say so. Else if stairs
    # down adjacent, say which direction. Else if a letter glyph (monster)
    # is adjacent and HP is healthy, suggest attack. Strictly directive;
    # the model still has to call the tool.
    hint = None
    # HP-critical override — fires regardless of stairs / monsters.
    if structured.status:
        hp = structured.status.get("hitpoints", 0)
        hp_max = structured.status.get("max_hitpoints", 1) or 1
        if hp / hp_max < 0.3 and hp > 0:
            hint = (
                f"HP critical ({hp}/{hp_max}). Options in order: `engrave_elbereth` "
                f"(scares most monsters) → `search(times=20)` in a safe corner to rest "
                f"and regenerate HP → `pray` if not on cooldown. Avoid melee until "
                f"HP is back above 70%."
            )
    if hint is None and under and "stairs DOWN" in under:
        hint = "You are on stairs down. Call `descend` now."
    elif hint is None and under and under.startswith("on tile:"):
        # Item under the player — suggest pickup.
        hint = f"Item here ({under}). Call `pickup` to grab it before moving on."
    else:
        for d, tile in adj.items():
            if "stairs DOWN" in tile:
                hint = f"Stairs down ({d}). Call `move(direction=\"{d}\")` to step onto them, then `descend`."
                break
        if hint is None:
            # Adjacent letter glyph == hostile (the obs renderer labels
            # monsters as their letter). HP-aware: only suggest engagement
            # when above 50% HP; otherwise suggest retreat.
            mon_dir = None
            for d, tile in adj.items():
                if len(tile) >= 1 and tile[0].isalpha() and tile not in ("@",):
                    # Skip pets — extract_adjacent now flags them when glyphs
                    # are available. Recommending `attack` on a pet would
                    # trigger the "really attack" peaceful prompt and damage
                    # alignment if confirmed.
                    if "PET" in tile:
                        continue
                    mon_dir = d
                    break
            if mon_dir is not None and structured.status:
                hp = structured.status.get("hitpoints", 0)
                hp_max = structured.status.get("max_hitpoints", 1) or 1
                if hp / hp_max >= 0.5:
                    hint = f"Hostile adjacent ({mon_dir}). Call `attack(direction=\"{mon_dir}\")` — your HP is healthy."
                else:
                    hint = f"Hostile adjacent ({mon_dir}) and HP is low ({hp}/{hp_max}). Consider `engrave_elbereth` or retreat with `move`."
    # Pet-blocking detection: when the message buffer says "X is in the way!"
    # the move failed because the pet/peaceful occupies the tile. Trace
    # 9071d001 had the model stuck in long pet-blocking loops. Override any
    # weaker hint with a clear "go around" directive.
    if structured.messages:
        for msg in structured.messages[-4:]:
            if "is in the way" in msg:
                hint = (
                    "A pet/peaceful is blocking your move. Walk a perpendicular "
                    "direction first to let it pass, or call `move(direction=\".\")` "
                    "to wait one turn."
                )
                break
    if hint:
        lines.append(f"=== HINT === {hint}")
        lines.append("")
    # Hostiles-in-sight: optional one-liner so the agent doesn't need to
    # scan the map to spot monsters. Skipped when no letter glyphs visible.
    if compact:
        from nethack_core.observations import extract_hostiles_in_sight, extract_visible_features
        # tty_chars not in StructuredObservation; pull from raw obs via state.
        if state is not None and "raw_obs" in state:
            try:
                features = extract_visible_features(state["raw_obs"].tty_chars)
                if features:
                    # Pre-parsed feature list with coordinates. Saves the
                    # model from scanning ASCII for `>`/`<`/`_`/`{`/`$`. The
                    # 9071d001 trace had the model confusing `<` for `>` and
                    # inventing `f = fireplace`; explicit feature naming with
                    # coordinates lets `move_to(x,y)` immediately.
                    lines.append(f"=== VISIBLE FEATURES === {'; '.join(features)}")
                    lines.append("")
                hostiles = extract_hostiles_in_sight(state["raw_obs"].tty_chars, getattr(state["raw_obs"], "glyphs", None))
                if hostiles:
                    lines.append(f"=== VISIBLE GLYPHS === {', '.join(hostiles)}")
                    lines.append("")
            except Exception:
                pass
    if structured.messages:
        lines.append("=== MESSAGES ===")
        msgs = _run_length_encode_messages(structured.messages) if compact else list(structured.messages)
        for m in msgs:
            lines.append(f"  {m}")
        lines.append("")
    if structured.menu:
        # Menus are auto-dismissed by the harness via ESC after each step;
        # if you see this block, dismissal didn't fully clear (rare).
        lines.append("=== MENU (harness will auto-dismiss; ignore) ===")
        for i, opt in enumerate(structured.menu):
            lines.append(f"  [{i}] {opt.description}")
        lines.append("")
    if structured.inventory_prompt:
        p = structured.inventory_prompt
        # Inventory prompts are auto-dismissed; eat/quaff/read take an `item`
        # arg and bundle the selection in-skill, so this block should not
        # normally appear.
        lines.append(f"=== PROMPT: {p['action']} (harness will auto-dismiss; pass `item` to eat/quaff/read) ===")
        for i, item in enumerate(p["items"]):
            lines.append(f"  [{i}] {item.description}")
        lines.append("")
    return "\n".join(lines)


# ---------- the env class ----------

class NetHackVerifiersEnv(vf.StatefulToolEnv):
    """
    Per-rollout state: a live NetHackCoreEnv plus character + cumulative scout count.

    We subclass StatefulToolEnv because each rollout owns a long-lived NLE
    instance that must be cleanly initialized in setup_state and torn down on
    completion.

    interface: "skill" (default) or "code". In code mode, `env_response` routes
    the model's `code(source=...)` tool call through `code_mode.run_user_code`,
    which executes against an `nh` namespace and produces a list of NLE actions
    that we then step.
    """

    def __init__(
        self,
        *args,
        interface: str = "skill",
        sub_lm=None,
        subgoal_proposer=None,
        # Compaction knobs (survey rec). Set via load_environment kwargs.
        compact_obs: bool = True,
        history_keep_full: int = 5,
        history_drop_after: int = 100,
        belief_state_interval: int = 25,
        journal_render_max_chars: int = 2000,
        **kwargs,
    ):
        self.interface = interface
        # Pluggable LM backends. Both default to None → the rollout-time code
        # falls back to the deterministic Offline* implementations. Swap in
        # prime-rl-backed clients by passing them here from load_environment.
        self.sub_lm = sub_lm
        self.subgoal_proposer = subgoal_proposer
        # Compaction knobs. compact_obs=False reverts to the v0.0.15-era
        # raw rendering (good for replay / debugging / A/B). The history /
        # belief-state / journal knobs let you trade off LM context size
        # against semantic fidelity per run.
        self.compact_obs = compact_obs
        self.history_keep_full = history_keep_full
        self.history_drop_after = history_drop_after
        self.belief_state_interval = belief_state_interval
        self.journal_render_max_chars = journal_render_max_chars
        super().__init__(*args, **kwargs)

    async def setup_state(self, state: vf.State) -> vf.State:
        task: dict = state["task"]
        tier_name: TierName = task.get("tier", "corridor_explore")
        seed: int = task.get("seed", random.randint(0, 2**31 - 1))
        spec = get_tier(tier_name)

        env = NetHackCoreEnv(
            task_name=spec.nle_task,
            max_episode_steps=spec.max_episode_steps,
            des_file=spec.des_file,
        )
        env.seed(core=seed, disp=seed)
        # NB: bootstrap_character() is currently a stub; once wired up it
        # auto-invokes #attributes and stores role/race/alignment in state.
        obs, meta = env.reset()
        from nethack_core.skills import bootstrap_character
        character = bootstrap_character(env)

        state["env"] = env
        state["character"] = character
        state["spec"] = spec
        state["meta"] = meta
        state["scout_tiles_seen"] = set()
        state["scout_delta"] = 0
        state["scout_reward_total"] = 0.0
        state["max_dlvl_reached"] = 1
        state["descent_count"] = 0
        state["raw_obs"] = obs
        state["structured_obs"] = shape_observation(obs, character)
        state["last_reward"] = 0.0
        state["terminated"] = False
        state["journal"] = Journal()
        # Pre-pin the tier's description as the agent's objective so the
        # goal stays in every obs (without forcing the model to call
        # pin_objective). For dynamic_subgoal, the proposer pin below
        # overrides this with the LM-proposed objective.
        if spec is not None and getattr(spec, "description", None):
            state["journal"].pin_objective(spec.description)
        if self.sub_lm is not None:
            state["sub_lm"] = self.sub_lm  # used by belief-state distillation
        if self.subgoal_proposer is not None:
            state["subgoal_proposer"] = self.subgoal_proposer

        # Dynamic-subgoal tier: ask the proposer for an episode-specific
        # termination predicate and bolt it onto the spec for env_response
        # to read like any other success_milestone. This is the autoresearch
        # axis: "can an LLM design its own curriculum given the wiki?"
        if tier_name == "dynamic_subgoal":
            from nethack_core.subgoals import compile_predicate, default_proposer
            proposer = state.get("subgoal_proposer") or default_proposer()
            subgoal = proposer.propose(role=character.get("role", "unknown"),
                                        obs=state["structured_obs"])
            milestone = compile_predicate(subgoal.termination_check)
            from dataclasses import replace
            state["spec"] = replace(spec, success_milestone=milestone)
            state["dynamic_subgoal"] = {
                "objective": subgoal.objective,
                "rationale": subgoal.rationale,
                "termination_check": subgoal.termination_check,
            }
            # Pin the objective into the journal so the agent sees it.
            state["journal"].pin_objective(subgoal.objective)

        return state

    async def env_response(self, messages: vf.Messages, state: vf.State) -> vf.Messages:
        # Parse the assistant's tool call from messages[-1].
        # In v0 we expect native function calling (OpenAI tool format).
        assistant_msg = messages[-1]
        # assistant_msg can be a dict (legacy) or a vf.AssistantMessage pydantic object (current).
        if isinstance(assistant_msg, dict):
            tool_calls = assistant_msg.get("tool_calls") or []
        else:
            tool_calls = getattr(assistant_msg, "tool_calls", None) or []
        if not tool_calls:
            # Filter harness-owned skills from the suggestion list — they
            # don't appear in the actual tool schema sent to the model.
            agent_tools = [s for s in list_skills() if s not in ("menu_option", "inventory_item")]
            return [vf.UserMessage(role="user", content="You must call a tool. Available tools: " + ", ".join(agent_tools))]

        # Apply the first tool call (NetHack is turn-based; we ignore multi-call this turn).
        # Verifiers passes tool calls in two shapes depending on version:
        #   old: dict {"function": {"name": ..., "arguments": "..."}}
        #   new: ToolCall pydantic model with flat .name / .arguments
        tc = tool_calls[0]
        import json
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            skill_name = fn.get("name", tc.get("name", "")) or ""
            raw_args = fn.get("arguments", tc.get("arguments", "{}"))
        else:
            fn = getattr(tc, "function", None)
            skill_name = (getattr(fn, "name", None) if fn is not None else getattr(tc, "name", "")) or ""
            raw_args = getattr(fn, "arguments", None) if fn is not None else getattr(tc, "arguments", "{}")

        # Defensive parsing: small models emit malformed args. Coerce to dict
        # so we never crash on dispatch.
        if raw_args is None or raw_args == "":
            skill_args = {}
        elif isinstance(raw_args, dict):
            skill_args = raw_args
        else:
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    skill_args = parsed
                else:
                    # Model emitted a non-dict (list, scalar, ...). Treat as empty
                    # and let the skill registry surface a friendly error.
                    skill_args = {}
            except (ValueError, TypeError):
                # Malformed JSON — same recovery path.
                skill_args = {}

        env: NetHackCoreEnv = state["env"]

        # Code-mode dispatch: if the model called the `code` tool, run the
        # source against the nh namespace and convert its action queue into
        # a SkillResult shape so the rest of env_response can stay unchanged.
        if self.interface == "code" and skill_name == "code":
            from nethack_core.code_mode import run_user_code
            from nethack_core.skills import SkillResult
            source = skill_args.get("source", "")
            cm_result = run_user_code(
                source, env, state["structured_obs"], journal=state.get("journal")
            )
            stdout = cm_result.stdout or ""
            err = f"\n[code error: {cm_result.error}]" if cm_result.error else ""
            feedback = (stdout + err).strip() or "(code executed; no stdout)"
            result = SkillResult(actions=cm_result.actions_taken, feedback=feedback)
        else:
            result = skill_registry.call(
                skill_name, env, state["structured_obs"], **skill_args
            )

        # Journal skills: apply the journal op and short-circuit the env step.
        # No NLE turn is consumed; the agent's next prompt reflects the change.
        if result.journal_op is not None:
            journal: Journal = state["journal"]
            feedback = result.journal_op(journal)
            state["scout_delta"] = 0  # no exploration happened
            obs_text = format_observation_as_chat(state["structured_obs"], journal, state=state, compact=self.compact_obs, journal_max_chars=self.journal_render_max_chars)
            if feedback:
                obs_text = f"[{feedback}]\n\n{obs_text}"
            return [vf.UserMessage(role="user", content=obs_text)]

        # Capture pre-step scout set size so scout_reward can return a per-step delta
        # rather than a cumulative count. See onboarding/scout_reward.md.
        scout_before = len(state["scout_tiles_seen"])
        # Capture pre-step player (x, y) so we can detect blocked moves.
        pre_pos = None
        try:
            pre_blstats = state["raw_obs"].blstats if state.get("raw_obs") is not None else None
            if pre_blstats is not None:
                pre_pos = (int(pre_blstats[0]), int(pre_blstats[1]))
        except (KeyError, IndexError, TypeError, AttributeError):
            pre_pos = None

        # Skills can return either NLE action enum values (107 == N) or task
        # action-set indices (1 == N for NetHackScore). The underlying gym
        # step expects indices, so convert at the boundary.
        action_indices = _to_action_indices(env, result.actions)

        # Step the underlying env through the action sequence the skill produced.
        # Multi-action skills (autoexplore, move_to) expand into many env.step
        # calls; we halt early on three conditions to give the model a chance
        # to react before walking into a dragon: HP-drop, hostile-in-sight,
        # explicit terminal. This is the "halt on hostile/HP-drop/hunger" item
        # from the project plan.
        total_reward = 0.0
        terminated = truncated = False
        info: dict = {}
        last_obs = state["raw_obs"]
        hp_before = state["structured_obs"].status.get("hitpoints", 0) if state.get("structured_obs") else 0
        halt_reason: Optional[str] = None
        for step_i, action in enumerate(action_indices):
            last_obs, r, terminated, truncated, info = env.step(action)
            total_reward += r
            # Scout reward: count newly-revealed dungeon tiles.
            for (x, y), ch in _iterate_visible_tiles(last_obs):
                if ch not in (b" ", b"\x00"):
                    state["scout_tiles_seen"].add((state["max_dlvl_reached"], x, y))
            if terminated or truncated:
                break
            # Status-aware halt: check after each step (cheap — just blstats).
            # Only enabled for multi-step skills (>=4 actions in a single tool
            # call) so single-key skills aren't penalized by the overhead.
            if len(action_indices) >= 4 and step_i + 1 < len(action_indices):
                halt_reason = _check_halt_condition(last_obs, hp_before)
                if halt_reason:
                    break
                # Also halt if a y/n / menu prompt opened mid-sequence — the
                # remaining action indices would be consumed as keystroke
                # answers to the prompt rather than continuing the intended
                # action sequence (e.g. autoexplore step 16 would answer
                # "Really attack?" as 'n' instead of moving NE).
                msg_bytes = last_obs.get("message") if isinstance(last_obs, dict) else None
                if msg_bytes is not None:
                    msg = bytes(msg_bytes).split(b"\x00", 1)[0].decode("ascii", errors="replace")
                    if "[yn" in msg or "--More--" in msg:
                        halt_reason = "prompt opened mid-sequence"
                        break

        scout_after = len(state["scout_tiles_seen"])
        state["scout_delta"] = scout_after - scout_before
        # Accumulate cumulative scout reward: the rubric scores once at end of
        # rollout, so a per-step `scout_delta` alone would only reflect the
        # final step. Sum here so scout_reward can report total exploration.
        state["scout_reward_total"] += state["scout_delta"] / 1000.0

        state["raw_obs"] = last_obs
        state["structured_obs"] = shape_observation(last_obs, state["character"])
        # Auto-dismiss any menu/inventory_prompt that's still open. Menus are
        # mechanical (--More--, level-up choice picker, multi-page item lists)
        # and were a huge time-sink for the LM agent: Qwen3.5-9B spent 42% of
        # turns on menu_option / inventory_item calls (often nonsensical) before
        # this hook. By auto-pressing ESC, the harness owns the menu-navigation
        # responsibility and the agent sees a clean post-menu observation on the
        # next turn. The `eat`/`quaff`/`read` skills now bundle item selection
        # in-skill, so intentional inventory prompts also resolve here.
        dismissed = 0
        esc_idx_list = _to_action_indices(env, [27])
        more_idx_list = _to_action_indices(env, [13])
        y_idx_list = _to_action_indices(env, [ord('y')])
        n_idx_list = _to_action_indices(env, [ord('n')])
        esc_action = esc_idx_list[0] if esc_idx_list else (more_idx_list[0] if more_idx_list else None)
        y_action = y_idx_list[0] if y_idx_list else esc_action
        n_action = n_idx_list[0] if n_idx_list else esc_action
        for _ in range(8):
            so = state["structured_obs"]
            yn = getattr(so, "yn_prompt", None)
            # Detect --More-- prompts in the message buffer too — they consume
            # the next keystroke, which would otherwise eat the model's
            # intended action. MORE/CR (13) acknowledges them.
            has_more = any("--More--" in m for m in (so.messages or []))
            if so.menu is None and so.inventory_prompt is None and yn is None and not has_more:
                break
            if yn is not None:
                ans = yn["answer"]
                action = y_action if ans == "y" else (n_action if ans == "n" else esc_action)
            elif has_more:
                # MORE prompts want CR/space, not ESC.
                action = more_idx_list[0] if more_idx_list else esc_action
            else:
                action = esc_action
            if action is None:
                break
            last_obs, _r, t2, tr2, _info = env.step(action)
            terminated = terminated or t2
            truncated = truncated or tr2
            state["raw_obs"] = last_obs
            state["structured_obs"] = shape_observation(last_obs, state["character"])
            dismissed += 1
            if terminated or truncated:
                break
        if dismissed:
            halt_reason = (halt_reason or "") + (f" menu auto-dismissed x{dismissed}" if not halt_reason else f" / menu auto-dismissed x{dismissed}")
            halt_reason = halt_reason.lstrip()
        state["last_reward"] = total_reward
        state["terminated"] = terminated or truncated
        # BALROG-style progression score (informational; not in rubric).
        # Tracks deepest (DL, XL) achieved as an empirical-ish P(ascend).
        from nethack_core.balrog import progression_score
        s = state["structured_obs"].status
        state["balrog_progression"] = progression_score(
            state["max_dlvl_reached"], s.get("experience_level", 1)
        )
        # Death/ascension detection from the game state, not raw NLE termination flag.
        _detect_terminal_outcome(last_obs, state)
        # Milestone-driven success: if the tier's success_milestone fires, we
        # treat the rollout as won and let success_reward pay out.
        spec = state.get("spec")
        if spec is not None and getattr(spec, "success_milestone", None) is not None:
            if spec.success_milestone.check(last_obs, state):
                state["succeeded"] = True
                state["terminated"] = True

        # Belief-state distillation (Track B v0.3): two trigger conditions.
        # 1) Level transition: summarize the prior level into the journal.
        # 2) Periodic (every BELIEF_STATE_INTERVAL turns): summarize the
        #    recent journal into a compact "belief_state" note so history-
        #    compaction can drop turns >100 without losing the LM's mental
        #    model. Survey rec #3.
        new_dlvl = state["structured_obs"].status.get("depth", 1)
        if new_dlvl > state["max_dlvl_reached"]:
            _maybe_distill(state, prior_dlvl=state["max_dlvl_reached"])
            # Count the descent here so descent_reward can read a cumulative
            # tally at end-of-rollout. (The rubric only fires score_rollout
            # once, so a per-step compare would lose every transition except
            # the last.)
            state["descent_count"] = state.get("descent_count", 0) + (new_dlvl - state["max_dlvl_reached"])
            state["max_dlvl_reached"] = new_dlvl  # update AFTER computing the level delta

        state["turn_count"] = state.get("turn_count", 0) + 1
        if self.belief_state_interval > 0 and state["turn_count"] > 0 and state["turn_count"] % self.belief_state_interval == 0:
            _maybe_belief_state_summary(state)

        # Move-blocked detection: `move(direction=...)` always reports "Moved
        # S." even when the action bumped a wall. The model can't tell from
        # feedback whether the step succeeded. Compare pre/post player (x, y)
        # from blstats; if a single-step move kept us in place, override the
        # feedback so the model knows to pick a different direction.
        if skill_name == "move" and len(action_indices) == 1 and pre_pos is not None and not terminated and not truncated:
            try:
                from nethack_core.skills import SkillResult as _SR
                post_blstats = last_obs.blstats if hasattr(last_obs, "blstats") else last_obs.get("blstats")
                if post_blstats is not None:
                    post_pos = (int(post_blstats[0]), int(post_blstats[1]))
                    if post_pos == pre_pos:
                        result = _SR(
                            actions=result.actions,
                            feedback=f"Move blocked at {pre_pos}: wall or obstacle in {skill_args.get('direction', '?')}. Pick a different direction or `search` if you suspect a hidden door.",
                            interrupted=result.interrupted,
                        )
            except (KeyError, IndexError, TypeError, AttributeError):
                pass

        # Attack-outcome detection: replace the generic "Moved W." feedback
        # with hit/miss/kill info pulled from the NLE message buffer. The
        # model doesn't otherwise know whether its swing landed.
        if skill_name == "attack":
            try:
                from nethack_core.skills import SkillResult as _SR
                msg_bytes = last_obs.message if hasattr(last_obs, "message") else last_obs.get("message")
                if msg_bytes is not None:
                    msg = bytes(msg_bytes).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
                    if msg:
                        outcome = None
                        msg_l = msg.lower()
                        if "you kill" in msg_l or "is killed" in msg_l:
                            outcome = f"Killed: {msg}"
                        elif "you hit" in msg_l or "you destroy" in msg_l:
                            outcome = f"Hit: {msg}"
                        elif "you miss" in msg_l:
                            outcome = f"Missed: {msg}"
                        elif "nothing here" in msg_l or "no monster" in msg_l:
                            outcome = f"No target: {msg}"
                        if outcome:
                            result = _SR(actions=result.actions, feedback=outcome, interrupted=result.interrupted)
            except (KeyError, IndexError, TypeError, AttributeError):
                pass

        # Autoexplore-loop detection: when autoexplore returns "short" feedback
        # repeatedly (frontier shrunk to 1-2 step paths near level edges), the
        # model often spam-calls it ignoring the tail hint. After N consecutive
        # short trips, emit a stronger interrupt hint at the TOP of the obs.
        # Trace 9071d001 showed 66 autoexplore calls with 7-long runs ignoring
        # in-skill tail tips.
        loop_hint: Optional[str] = None
        if skill_name == "autoexplore" and result.feedback and "short" in result.feedback:
            state["consecutive_short_autoexplore"] = state.get("consecutive_short_autoexplore", 0) + 1
            n = state["consecutive_short_autoexplore"]
            if n >= 3:
                loop_hint = (
                    f"[autoexplore-loop: {n} short trips in a row. "
                    "Switch tactic: `search` adjacent walls, or `move_to(x,y)` "
                    "a specific feature, or pick a direction with `move`.]"
                )
        else:
            state["consecutive_short_autoexplore"] = 0

        # Build observation message for the model.
        obs_text = format_observation_as_chat(state["structured_obs"], state["journal"], state=state, compact=self.compact_obs, journal_max_chars=self.journal_render_max_chars)
        prefix_parts = []
        if loop_hint:
            prefix_parts.append(loop_hint)
        if halt_reason:
            prefix_parts.append(f"[autohalt: {halt_reason}]")
        if result.feedback:
            prefix_parts.append(f"[{result.feedback}]")
        if prefix_parts:
            obs_text = "\n".join(prefix_parts) + "\n\n" + obs_text
        return [vf.UserMessage(role="user", content=obs_text)]

    async def is_completed(self, state: vf.State) -> bool:
        return bool(state.get("terminated"))

    async def get_prompt_messages(self, state: vf.State):
        """Override the verifiers default to compact older user-message content
        (i.e. our prior turn observations) before sending to the LM. This is
        the biggest token-bill win: chat history grew linearly in turns,
        re-sending the full tty grid (~25k tok/turn) every single time. After
        compaction:
          * last K=5 turns: full fidelity
          * turns K..100: replaced with a one-line "[turn N: <summary>]"
          * turns >100: dropped entirely
        Mirrors SWE-agent's "elide all but last 5" and Glyphbox's 10/100
        thresholds (see docs/PROMPTING_SURVEY.md).
        """
        messages = await super().get_prompt_messages(state)
        return _compact_chat_history(messages, keep_full=self.history_keep_full, drop_after=self.history_drop_after)

    def update_tool_args(self, tool_args: dict, messages, state) -> dict:
        """
        Required by StatefulToolEnv. We dispatch tool calls manually inside
        `env_response` (because each skill has a custom signature involving
        the env handle + structured observation), so this hook is a no-op:
        we never let the base class's `call_tool()` route get used.
        """
        return tool_args


# ---------- helpers ----------


def _compact_chat_history(messages, keep_full: int = 5, drop_after: int = 100):
    """Compact older user (env-response) messages in-place so the chat doesn't
    grow without bound. Assistant messages are kept verbatim — their tool_calls
    matter for downstream replay. Only the *content* of user messages older
    than `keep_full` turns is rewritten.

    Compaction tiers:
      - turn distance ≤ keep_full: full fidelity (unchanged)
      - keep_full < distance ≤ drop_after: one-line summary
      - distance > drop_after: message dropped entirely

    Returns a NEW list so we never mutate state["trajectory"].
    """
    # Count from the end. "Turn distance" = how many user messages back this is.
    out = list(messages)
    # Walk backwards over user messages to compute distance.
    user_indices = [i for i, m in enumerate(out) if _msg_role(m) == "user"]
    if len(user_indices) <= keep_full:
        return out
    # Older user messages we want to compact (oldest first up to threshold).
    to_compact = user_indices[: -keep_full]
    to_drop_indices = set()
    for distance_from_end, idx in enumerate(reversed(to_compact), start=keep_full + 1):
        if distance_from_end > drop_after:
            to_drop_indices.add(idx)
            continue
        # One-line summary: keep prefix tags ([autohalt: ...], [feedback: ...])
        # and HP/Turn/Dlvl status line; drop everything else.
        summary = _one_line_summary(_msg_content(out[idx]), distance_from_end)
        out[idx] = _replace_content(out[idx], summary)
    if to_drop_indices:
        # Replace dropped chunks with a single elision marker if there's anything to drop.
        n_dropped = len(to_drop_indices)
        out = [m for i, m in enumerate(out) if i not in to_drop_indices]
        # Insert a single elision marker at the start (after system prompt if present).
        from typing import cast
        insert_at = 1 if out and _msg_role(out[0]) == "system" else 0
        out.insert(insert_at, vf.UserMessage(
            role="user",
            content=f"[elided {n_dropped} older turns; see journal for context]",
        ))
    # Second pass: collapse consecutive compacted user messages with the same
    # status signature. In the 9071d001 trace, 90 user msgs were literally
    # "[turn -X] HP: 14/14 AC: 4 Dlvl: 1 ..." with the same HP/AC/Dlvl — pure
    # token noise. We shrink runs to "[turn -Y] (status unchanged)".
    out = _dedupe_compacted_runs(out)
    return out


_STATUS_SIG_RE = re.compile(r"HP:\s*(\d+/\d+)\s+AC:\s*(-?\d+)\s+Dlvl:\s*(\d+)")


def _compacted_status_signature(content: str) -> Optional[tuple]:
    """Return (hp_ratio, ac, dlvl, has_feedback) for a compacted user message,
    or None if the message isn't recognized as compacted-only (i.e., still has
    a MAP block, or is an elision marker, or has unique feedback)."""
    if "=== MAP ===" in content or "elided" in content[:30]:
        return None
    if not content.lstrip().startswith("[turn -"):
        return None
    # Any non-trivial bracketed feedback (e.g. [Moved S.], [Attack hit]) makes
    # this turn unique — don't collapse.
    head = content.split("\n", 1)[0]
    # Strip leading [turn -N]
    rest = re.sub(r"^\[turn -\d+\]\s*", "", head)
    fb_match = re.match(r"\[([^\[\]]{1,80})\]", rest)
    has_feedback = bool(fb_match and "turn -" not in fb_match.group(1))
    sig = _STATUS_SIG_RE.search(content)
    if not sig:
        return None
    return (sig.group(1), sig.group(2), sig.group(3), has_feedback)


def _dedupe_compacted_runs(messages):
    """Collapse consecutive compacted user messages with identical
    HP/AC/Dlvl signatures and no per-turn feedback into terse `[turn -Y]
    (unchanged)` placeholders. Keeps the first message in each run intact
    so the model can read the actual status; later messages just mark
    that nothing changed.

    Does not change message count or assistant messages — purely shrinks
    redundant content.
    """
    out = list(messages)
    last_sig: Optional[tuple] = None
    for i, m in enumerate(out):
        if _msg_role(m) != "user":
            continue
        content = _msg_content(m)
        sig = _compacted_status_signature(content)
        if sig is None:
            last_sig = None
            continue
        # If feedback present, keep full and reset run.
        _, _, _, has_feedback = sig
        if has_feedback:
            last_sig = sig
            continue
        if last_sig is not None and sig[:3] == last_sig[:3]:
            # Same status as previous compacted msg: shrink.
            turn_match = re.match(r"\[turn -(\d+)\]", content)
            label = turn_match.group(0) if turn_match else "[turn -?]"
            out[i] = _replace_content(m, f"{label} (unchanged)")
        last_sig = sig
    return out


def _msg_role(m) -> str:
    """Pull role from either a dict-shaped message or a pydantic Message."""
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


def _msg_content(m) -> str:
    if isinstance(m, dict):
        c = m.get("content", "")
    else:
        c = getattr(m, "content", "")
    return c if isinstance(c, str) else ""


def _replace_content(m, new_content: str):
    """Return a copy of `m` with content swapped, preserving role + pydantic class."""
    if isinstance(m, dict):
        out = dict(m)
        out["content"] = new_content
        return out
    # pydantic: use model_copy(update=...).
    try:
        return m.model_copy(update={"content": new_content})
    except Exception:
        return vf.UserMessage(role=_msg_role(m), content=new_content)


def _one_line_summary(content: str, turn_distance: int) -> str:
    """Squash a full obs_text into one line. Heuristics:
       - Keep the STATUS line ("HP: x/y AC: z Dlvl: d Turn: t ...") if present.
       - Keep any [autohalt: ...] / [...] feedback prefix.
       - Otherwise just emit a placeholder.

    IMPORTANT (bug-fix 2026-05-16): `get_prompt_messages` walks the FULL
    chat history every turn, so already-compacted messages get re-fed into
    this function each turn. Previously, the loop would re-pick the
    `[turn -N]` label as `feedback` and prepend a new `[turn -K]` to it
    each round — after many turns, the message becomes a useless chain
    like "[turn -92] [turn -91] [turn -90] ... [turn -7]" with no content.
    Now we detect already-compacted messages and emit a single fresh
    label, dropping the chain. Idempotent.
    """
    stripped_content = content.strip()
    looks_compacted = (
        stripped_content.startswith("[turn -")
        and "=== " not in stripped_content
        and "MAP" not in stripped_content
    )
    if looks_compacted:
        # Already compacted: extract whatever feedback/status we saved earlier
        # and re-emit with the fresh distance label. Without this, every
        # subsequent compaction round drops the [Moved S.] / [Picked up]
        # marker, erasing the agent's action audit-log.
        feedback_part = ""
        hp_part = ""
        # Drop the leading "[turn -N] " then scan the remainder.
        remainder = re.sub(r"^\[turn -\d+\]\s*", "", stripped_content)
        # Feedback is a short bracketed token like "[Moved S.]" or "[Picked up]"
        fb_match = re.match(r"(\[[^\[\]]{1,80}\])\s*", remainder)
        if fb_match and "[turn -" not in fb_match.group(1):
            feedback_part = fb_match.group(1)
            remainder = remainder[fb_match.end():]
        # Status line: "HP: x/y AC: z ..."
        hp_match = re.search(r"HP:\s*\d+/\d+[^\n]*", remainder)
        if hp_match:
            hp_part = hp_match.group(0).strip()
        parts = [f"[turn -{turn_distance}]"]
        if feedback_part: parts.append(feedback_part)
        if hp_part: parts.append(hp_part)
        return " ".join(parts)

    status_line = ""
    feedback = ""
    for line in content.splitlines()[:25]:  # cap scan; obs is short prefix
        line = line.strip()
        # Only treat short bracketed lines as feedback — not chained turn labels.
        if line.startswith("[") and line.endswith("]") and len(line) < 200 and "[turn -" not in line:
            feedback = line
        if line.startswith("HP: "):
            status_line = line
            break
    parts = [f"[turn -{turn_distance}]"]
    if feedback:
        parts.append(feedback)
    if status_line:
        parts.append(status_line)
    return " ".join(parts)


def _check_halt_condition(raw_obs, hp_before: int) -> Optional[str]:
    """Per-step halt for multi-action skills. Returns a short reason string
    if the model should regain control NOW, or None to continue.

    Conditions:
      - HP dropped by ≥25% of the pre-skill value (we're being hit).
      - Hunger blstat indicates Weak/Fainting (need to eat).
      - HP/maxHP < 0.3 (precarious situation).
    """
    try:
        # NLE blstats indices: 10=HP, 11=maxHP, 21=hunger (0=Satiated/1=Normal/...)
        # See nle/nethack/nethack.py:BLStats.
        blstats = raw_obs.get("blstats") if isinstance(raw_obs, dict) else None
        if blstats is None:
            return None
        hp = int(blstats[10])
        max_hp = max(int(blstats[11]), 1)
        hunger = int(blstats[21]) if len(blstats) > 21 else 1
    except (KeyError, IndexError, TypeError):
        return None

    if hp_before > 0 and hp <= hp_before * 0.75:
        return f"HP dropped {hp_before}→{hp}"
    if hp <= max_hp * 0.3:
        return f"HP critical ({hp}/{max_hp})"
    if hunger >= 4:  # Weak (4) or Fainting (5) or Starving (6)
        return f"hunger level {hunger}"
    return None


BELIEF_STATE_INTERVAL = 25
"""Every N turns, call SubLM.summarize on the journal+status and store the
result as a `belief_state:<turn>` note. Allows history-compaction to drop
older turns without losing semantic context. Survey recommendation #3."""


def _maybe_belief_state_summary(state: dict) -> None:
    """Periodic belief-state distillation. Best-effort — silently skips on
    SubLM error so it never breaks a rollout.

    When the configured sub_lm is the OfflineSubLM stub (default), we skip
    the stub call and record a concrete status snapshot instead. The stub's
    "[offline-summary] ..." output isn't useful to the agent; a status
    snapshot at least surfaces HP/dlvl/turn at a known prior moment.
    """
    journal = state.get("journal")
    if journal is None:
        return
    try:
        s = state.get("structured_obs")
        turn = state.get("turn_count", 0)
        # Concrete status snapshot — useful regardless of SubLM backend.
        if s is not None:
            status_snap = (
                f"HP {s.status.get('hitpoints','?')}/{s.status.get('max_hitpoints','?')} "
                f"AC {s.status.get('armor_class','?')} "
                f"Dlvl {s.status.get('depth','?')} "
                f"Turn {s.status.get('time','?')} "
                f"max_dlvl={state.get('max_dlvl_reached','?')} "
                f"descents={state.get('descent_count',0)}"
            )
        else:
            status_snap = "(no obs)"

        # If a real (non-Offline) SubLM is wired, use its richer summary.
        sub_lm = state.get("sub_lm")
        from nethack_core.code_mode import OfflineSubLM
        if sub_lm is not None and not isinstance(sub_lm, OfflineSubLM):
            ctx_lines = [status_snap]
            for k, v in journal.notes.items():
                ctx_lines.append(f"- {k}: {v}")
            ctx = "\n".join(ctx_lines)
            try:
                summary = sub_lm.summarize(ctx, query=f"belief state at turn {turn}")
                journal.add_note(f"belief_state:t{turn}", summary)
                return
            except Exception:
                pass  # fall through to status snapshot

        journal.add_note(f"belief_state:t{turn}", status_snap)
    except Exception:
        pass


def _maybe_distill(state: dict, prior_dlvl: int) -> None:
    """Belief-state distillation hook. Calls the SubLM (default: Offline)
    to summarize what happened on `prior_dlvl` and adds it to the journal
    as `dlvl_<n>_summary`. Cheap when the SubLM is offline; nontrivial
    when wired to a real inference server.
    """
    journal = state.get("journal")
    if journal is None:
        return
    try:
        from nethack_core.code_mode import _default_sub_lm
        sub_lm = state.get("sub_lm") or _default_sub_lm()
        ctx_lines = []
        for k, v in journal.notes.items():
            ctx_lines.append(f"- {k}: {v}")
        ctx = "\n".join(ctx_lines) if ctx_lines else "(no notes recorded on this level)"
        summary = sub_lm.summarize(ctx, query=f"key events on dlvl {prior_dlvl}")
        journal.add_note(f"dlvl_{prior_dlvl}_summary", summary)
    except Exception:
        # Distillation is best-effort; don't break the rollout.
        pass


def _to_action_indices(env: NetHackCoreEnv, actions: list[int]) -> list[int]:
    """Convert NLE action enum values to indices into the task's action set.

    Skills built before we settled on indices return enum values (107, 108, ...).
    Skills built via pathfinding go through the same conversion already. This
    function is the single point that normalizes everything to indices.

    Any enum value not present in the action set is silently dropped — better
    to lose an action than to crash mid-rollout with `IndexError`.
    """
    if not actions:
        return []
    enum_to_idx = {int(a): i for i, a in enumerate(env.underlying.unwrapped.actions)}
    out: list[int] = []
    for a in actions:
        a = int(a)
        # If the value is already a small index (< len(actions)) and matches
        # the action set, accept it. Otherwise look up by enum value.
        if a in enum_to_idx:
            out.append(enum_to_idx[a])
        elif 0 <= a < len(enum_to_idx):
            out.append(a)
    return out


def _iterate_visible_tiles(obs):
    """Yield ((x, y), char) for currently-visible map tiles."""
    chars = obs.chars  # (21, 79)
    for y in range(chars.shape[0]):
        for x in range(chars.shape[1]):
            yield (x, y), bytes([int(chars[y, x])])


# ---------- rewards ----------

@vf.reward(weight=1.0)
async def scout_reward(state: vf.State) -> float:
    """
    Total normalized tiles scouted across the rollout.

    Verifiers' `Rubric.score_rollout` runs once at end of rollout. Returning
    the last step's `scout_delta` alone effectively reports only the very
    last action's exploration — every prior tile discovery is invisible to
    the eval harness. So env_response accumulates `scout_reward_total` each
    step (delta/1000) and we return that running sum. Old call sites that
    only set `scout_delta` (unit tests) still work as a fallback.
    """
    if "scout_reward_total" in state:
        return float(state["scout_reward_total"])
    return float(state.get("scout_delta", 0)) / 1000.0


@vf.reward(weight=10.0)
async def descent_reward(state: vf.State) -> float:
    """+1 per new dungeon level reached this episode.

    env_response increments `descent_count` whenever max_dlvl advances; we
    return the running tally. (A per-step comparison here would always read
    `depth == max_dlvl_reached` because env_response updates max_dlvl first.)
    """
    if "descent_count" in state:
        return float(state["descent_count"])
    # Back-compat for unit tests that set max_dlvl_reached + structured_obs.
    s = state.get("structured_obs")
    if s is None:
        return 0.0
    dlvl = s.status.get("depth", 1)
    if dlvl > state["max_dlvl_reached"]:
        state["max_dlvl_reached"] = dlvl
        return 1.0
    return 0.0


@vf.reward(weight=100.0)
async def success_reward(state: vf.State) -> float:
    """
    +1 if the tier's success_milestone fired this episode. Distinct from
    `ascension_reward` (which weight=1000) because milestone success is a
    rung on the curriculum, not the endgame.
    """
    return 1.0 if state.get("succeeded") else 0.0


@vf.reward(weight=1000.0)
async def ascension_reward(state: vf.State) -> float:
    """
    The big one. +1 when the player ascends (escapes the dungeon with the
    Amulet of Yendor), 0 otherwise. _detect_terminal_outcome in env_response
    sets state["ascended"]=True when the standard ascension messages appear.
    """
    return 1.0 if state.get("ascended") else 0.0


# ---------- terminal outcome detection ----------

# NetHack-3.6 prints these phrases on the final screen. We treat any of them
# as proof of ascension; the death case is symmetric (a player who didn't
# ascend but did die has state["died"]=True so we can attribute the outcome).
_ASCENSION_MARKERS = (
    "ascended to demigod",
    "ascended to demigoddess",
    "with the Amulet",
    "offered the Amulet",
)
_DEATH_MARKERS = (
    "killed by",
    "starved to death",
    "petrified by",
    "drowned",
    "quit the game",
    "Do you want your possessions identified",
)


def _decode_tty(obs) -> str:
    """Render the full tty into a single string for marker-scanning."""
    return "\n".join(
        "".join(chr(c) for c in row) for row in obs.tty_chars
    )


def _detect_terminal_outcome(obs, state: dict) -> None:
    """
    Inspect the last observation to determine death vs ascension. Mutates
    state in place. Called every step (cheap) so the reward functions can
    read precomputed booleans.
    """
    state.setdefault("ascended", False)
    state.setdefault("died", False)
    if state["ascended"] or state["died"]:
        return  # terminal outcomes are absorbing

    screen = _decode_tty(obs)
    if any(m in screen for m in _ASCENSION_MARKERS):
        state["ascended"] = True
        state["terminated"] = True
        return
    if any(m in screen for m in _DEATH_MARKERS):
        state["died"] = True
        state["terminated"] = True


# ---------- load_environment ----------

def _build_task_dataset(tier: Optional[TierName], n_examples: int, seed_base: int) -> Dataset:
    """Each row is one starting condition."""
    rng = random.Random(seed_base)
    if tier is None:
        tiers = list_tiers()
    else:
        tiers = [tier]
    rows = []
    for i in range(n_examples):
        t = rng.choice(tiers)
        spec = get_tier(t)
        rows.append({
            "prompt": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Task: {spec.description}\nSuccess: {spec.success_criterion}\n\nBegin."},
            ],
            "task": {"tier": t, "seed": rng.randint(0, 2**31 - 1)},
            "info": {"tier": t, "spec_description": spec.description},
        })
    return Dataset.from_list(rows)


def load_environment(
    tier: Optional[str] = "corridor_explore",
    n_examples: int = 256,
    seed: int = 0,
    max_turns: int = 200,
    interface: str = "skill",
    sub_lm=None,
    subgoal_proposer=None,
    compact_obs: bool = True,
    history_keep_full: int = 5,
    history_drop_after: int = 100,
    belief_state_interval: int = 25,
    journal_render_max_chars: int = 2000,
    **kwargs: Any,
) -> vf.Environment:
    """
    Entrypoint used by `vf-eval` and prime-rl.

    Args:
        tier: curriculum tier name, or None for uniform sampling across all tiers.
        n_examples: dataset size for training rollouts / evaluation.
        seed: RNG seed for which (tier, episode-seed) pairs get sampled.
        max_turns: per-rollout turn cap (LM turns, not in-game turns).
        interface: "skill" (default — one tool per skill, OpenAI function-calling)
            or "code" (a single `code` tool that runs sandboxed Python against
            an `nh` namespace; the Track B / RLM-research path).
        compact_obs: enable per-turn observation compaction (strip blank tty rows,
            glyph-run encoding, inventory diff). Default True; set False for raw v0.0.15
            rendering (replay/debugging).
        history_keep_full: number of most-recent turns kept at full fidelity in the
            LM prompt (older turns get a one-line summary or are dropped).
        history_drop_after: turns older than this distance are dropped behind a
            single elision marker.
        belief_state_interval: every N turns, SubLM.summarize is invoked and the
            result added to the journal as belief_state:tN. Set to 0 to disable.
        journal_render_max_chars: soft cap on per-turn journal block size; older
            non-belief-state notes get elided when over the cap.
    """
    dataset = _build_task_dataset(tier, n_examples, seed)
    rubric = vf.Rubric(funcs=[scout_reward, descent_reward, success_reward, ascension_reward])

    if interface == "skill":
        tool_callables = _build_skill_adapter_callables()
    elif interface == "code":
        tool_callables = [_code_tool_adapter()]
    else:
        raise ValueError(f"Unknown interface={interface!r}; expected 'skill' or 'code'.")

    return NetHackVerifiersEnv(
        dataset=dataset,
        rubric=rubric,
        tools=tool_callables,
        max_turns=max_turns,
        interface=interface,
        sub_lm=sub_lm,
        subgoal_proposer=subgoal_proposer,
        compact_obs=compact_obs,
        history_keep_full=history_keep_full,
        history_drop_after=history_drop_after,
        belief_state_interval=belief_state_interval,
        journal_render_max_chars=journal_render_max_chars,
        **kwargs,
    )


def _code_tool_adapter():
    """The single 'code' tool exposed in interface='code' mode."""
    def code(source: str) -> str:
        """Execute Python against the `nh` namespace.

        Available: nh.move/attack/descend/search/pickup/move_to/autoexplore,
        nh.add_note/recall, nh.wiki_lookup/wiki_search, nh.status/inventory/
        map_view/character. Constants: Direction.{N,NE,E,SE,S,SW,W,NW,WAIT},
        Position(x, y). Imports and dunder access are blocked. Stdout returns
        as the tool result. 5s wallclock cap.
        """
        return ""  # never called directly; env_response routes the source.

    return code


def _build_skill_adapter_callables() -> list:
    """
    Build one callable per registered skill with the right __name__, doc, and
    annotations so verifiers' tool-schema introspection works.

    The callables are stubs: calling them raises (we want a loud error if
    something ever bypasses `env_response` and tries to invoke them).
    """
    import inspect
    from typing import Optional as _Opt

    # Skills the harness owns (never exposed as agent tools). Menu/inventory
    # selection is auto-dismissed in env_response; eat/quaff/read take an
    # `item` arg and bundle the selection in-skill. Exposing these as agent
    # tools caused Qwen3.5-9B to spend 42% of turns on spurious menu calls.
    _HARNESS_OWNED = {"inventory_item", "menu_option"}
    out = []
    for name, schema in skill_registry.all_schemas().items():
        if name in _HARNESS_OWNED:
            continue
        params = schema.get("parameters", {}) or {}
        out.append(_make_skill_adapter(name, schema.get("description", ""), params))
    return out


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _make_skill_adapter(name: str, description: str, params: dict):
    """Create a callable that exposes the schema verifiers expects."""
    import inspect

    # Build a signature with parameters in declared order.
    sig_params = []
    annotations: dict = {}
    for pname, pschema in params.items():
        ptype = _TYPE_MAP.get(pschema.get("type", "string"), str)
        annotations[pname] = ptype
        default = pschema.get("default", inspect.Parameter.empty)
        sig_params.append(inspect.Parameter(
            pname,
            inspect.Parameter.KEYWORD_ONLY,
            default=default,
            annotation=ptype,
        ))

    def _adapter(**kwargs):
        raise RuntimeError(
            f"Skill adapter {name!r} was invoked directly; this should not "
            "happen — env_response dispatches via skill_registry.call()."
        )

    _adapter.__name__ = name
    _adapter.__doc__ = description
    _adapter.__signature__ = inspect.Signature(parameters=sig_params)
    _adapter.__annotations__ = annotations
    return _adapter
