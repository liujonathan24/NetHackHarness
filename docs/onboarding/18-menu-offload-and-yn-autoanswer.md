# 18 — Menu offload + y/n auto-answer (v0.0.35 → v0.0.46)

## Problem

After v0.0.34 shipped the trace-driven format fixes (UNDER PLAYER, GLYPH
KEY, descend short-circuit) the next Qwen3.5-9B local eval showed
**62/147 turns (42%)** spent on `menu_option` calls — and another 17 on
`inventory_item`. The model was treating any in-game prompt as a menu
requiring tool selection. Sampling the model's reasoning around one
spurious call:

> The game is asking "Really attack the little dog? [yn] (n)" — this is
> a query prompt, not an inventory prompt. … This is a menu-style
> prompt where I need to choose. … Let me assume index 0 for no, index
> 1 for yes. I'll say no (0) …

The model literally reasoned its way *into* calling `menu_option(0)`
for a single-keystroke y/n prompt. Repeated 62 times per rollout.

User direction: *"Can we avoid allowing opening the menu? That is a
known area that we may want to offload to the harness rather than the
agent."*

## Fix

Menus and inventory prompts are **mechanical** — they only need a
keystroke (the letter for inventory choice, ESC to dismiss). There's
no judgment call in "press space on --More--", and "yes/no" for
"Really attack?" is determined by intent (we already asked to attack).
This makes them perfect candidates for the harness, not the agent.

### Changes (v0.0.35)

1. **Removed `menu_option` and `inventory_item` from the agent's tool
   list.** They stay in the `SkillRegistry` for internal use (e.g.
   tests), but the verifiers `tools` list filters them out via a
   `_HARNESS_OWNED` set in `_build_skill_adapter_callables`.

2. **Auto-dismiss in `env_response`.** After applying the model's
   action sequence, a small loop checks `state["structured_obs"]` for
   `menu` / `inventory_prompt` / `yn_prompt`. If any is set, the
   harness presses the right key (letter for inventory, y/n per
   policy, ESC fallback) up to 8 times. The model sees a clean
   post-prompt observation on its next turn.

3. **`eat` / `quaff` / `read` get an `item` arg.** Substring of the
   item description or its inventory letter. The skill resolves to a
   letter, sequences `[cmd_key, letter]`, and if no item matches
   (e.g. you asked to eat with no food) the turn is NOT consumed —
   the model sees a candidate list and can retry.

### Changes (v0.0.36 – v0.0.46)

- v0.0.36: `item` made optional in schema (`"default": None`).
- v0.0.37: new `=== HINT ===` block in obs (next-action directive for
  stairs).
- v0.0.38: dispatcher arg-collision fix (positional-only params; strip
  `name`/`env`/`obs` from kwargs).
- v0.0.39: y/n prompt auto-answer with policy table.
- v0.0.40: dispatcher type coercion (`"5"` → 5) + AttributeError catch.
- v0.0.41: autoexplore dead-end tip (`search` for hidden passages).
- v0.0.42-43: HINT extended to adjacent monsters (HP-aware).
- v0.0.44: direction aliases ('north'/'up'/'east'/etc.).
- v0.0.45: expanded y/n policy table.
- v0.0.46: autoexplore short-path tail-hint.

## y/n policy table

Auto-answer is keyed on substring matches against the prompt text.
Default policy when nothing matches: use the parenthesized default
(`[yn] (n)` → `n`); otherwise ESC.

| Pattern | Answer | Reason |
|---------|--------|--------|
| `really attack` | y | We asked to attack |
| `continue?` | y | Don't interrupt valid action |
| `stop eating` | y | Conserve food |
| `swap places` | y | Friendly NPC pass-through |
| `force fight`, `force attack` | y | Player intent unambiguous |
| `pick up` | y | Auto-pickup is safe |
| `see?` | y | Inventory display |
| `really quit`, `really save` | n | Don't end the rollout |
| `die?` | n | Don't suicide |
| `stop praying` | n | Let prayer complete |
| `abort` | n | Don't cancel |
| `throw away` | n | Don't destroy items |

## Validation

Qwen3.5-9B, `corridor_explore`, `max_turns=100`, same seed across runs:

| metric | v0.0.33 (broken) | v0.0.40 (fixed) | Δ |
|---|---|---|---|
| scout_reward | 0.06 | **0.163** | +172% |
| descend_calls | 0 | **1** | first non-zero! |
| menu_option_calls | 62 (42% of turns) | 0 (removed) | -∞ |
| inventory_item_calls | 17 | 0 (removed) | -∞ |
| autoexplore_calls | 10 | **107** | +970% |
| attack_calls | 12 (mostly wasted) | 1 (effective) | quality up |

Every LM turn is now spent on actual gameplay. **262 tests green.**

## Files touched

- `nethack_core/skills.py`: `eat`/`quaff`/`read` take `item` arg;
  `_normalize_direction` for aliases; dispatcher rename + coercion.
- `nethack_core/observations.py`: new `extract_yn_prompt` + policy
  patterns; `StructuredObservation.yn_prompt` field.
- `environments/nethack/nethack.py`: auto-dismiss loop in `env_response`
  (esc/y/n actions); `_HARNESS_OWNED` filter in adapter builder;
  `=== HINT ===` block in `format_observation_as_chat`; SYSTEM_PROMPT
  updated.
- `tests/test_skills.py`: 9 new tests.
- `tests/test_observations.py`: 5 new yn_prompt tests.
- `tests/test_integration.py`: assert tools are NOT exposed.

## Future work

- The y/n policy table is hand-crafted. If new prompt patterns show up
  in traces (e.g. role-specific dialog), extend `_YN_YES_PATTERNS` /
  `_YN_NO_PATTERNS`. Conservative default (ESC) keeps unknown prompts
  safe.
- For `eat`/`quaff`/`read`, the `item` resolution uses substring
  matching on the description. If multiple items match, we pick the
  first — could surface a disambiguation feedback in the future, but
  none of the rollouts to date have hit that case.
- HINT currently only fires for stairs and monsters. Could extend to:
  "low HP — `pray` for healing" once we track prayer cooldown.
