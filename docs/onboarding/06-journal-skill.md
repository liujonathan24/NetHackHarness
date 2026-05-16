# The journal: structured agent memory

**Status:** Shipped in `nethack_core/journal.py` + new skills in
`nethack_core/skills.py` as of Day 3. Tested in `tests/test_journal.py`.

## Why this matters more than it looks like it should

Pokemon-bench (Claude/Gemini Plays Pokemon, late 2025 → 2026) hammered home
one finding: in long-horizon games, **the agent's scratchpad is load-bearing**.
Without persistent notes, the model has to re-derive map state, monster
locations, and strategy on every turn from raw observation history. With
notes, it accumulates knowledge and can act on it.

glyphbox validated the same in NetHack specifically (Jan 2026): exposing
`add_note` / `recall` to the model got GPT 5.2 to dlvl 10 / 12.56% BALROG
progression, against single-digit progression without it.

This is also where Alex's RLM angle starts to bite. Once you have a real
journal as a tool, swapping `recall(query)` from "substring search" to "sub-LM
call over journal + observation history" is a one-line interface change —
the agent doesn't notice. We default to substring now; the upgrade path is
clear.

## The API

Three tools, all registered through the existing `SkillRegistry`:

```python
add_note(key: str, text: str)         # write/overwrite a keyed note
recall(query: str)                    # return notes whose key or text matches
pin_objective(text: str)              # set the always-rendered top objective
```

The data model (in `nethack_core/journal.py`):

```python
@dataclass
class Journal:
    notes: dict[str, str] = field(default_factory=dict)
    objective: Optional[str] = None
```

Per-rollout. Lives in `state["journal"]`. The verifiers env initializes it in
`setup_state` and reads it in `format_observation_as_chat` so the journal
block appears at the top of every observation.

## How a journal-skill call flows

The harness layer (`environments/nethack/nethack.py::env_response`) checks if
the skill returned a `journal_op`:

```python
if result.journal_op is not None:
    journal = state["journal"]
    feedback = result.journal_op(journal)
    state["scout_delta"] = 0  # no exploration happened
    obs_text = format_observation_as_chat(state["structured_obs"], journal)
    if feedback:
        obs_text = f"[{feedback}]\n\n{obs_text}"
    return [{"role": "user", "content": obs_text}], state
```

Key properties:

- **No NLE turn is consumed.** Journal ops happen between game turns. The
  game state is unchanged.
- **`scout_delta` is reset.** No exploration happened, so the scout reward
  doesn't pay for a journal write.
- **Feedback is shown to the model.** The string returned by the journal op
  (e.g. `"Note 'altar' added."`) is prepended to the next observation so the
  model knows the op landed.
- **The journal is always rendered.** Once the journal has any content,
  `format_observation_as_chat` puts a `=== JOURNAL ===` block at the top of
  every observation. Empty journal = no block. So early-game observations
  aren't bloated with empty memory state.

## Why a dict, not append-only?

The model needs to *overwrite* stale notes. NetHack state changes:

- "dragon was on dlvl 3" → "dragon killed"
- "shopkeeper angry" → "shopkeeper paid, calm"
- "altar dlvl 4 was unaligned" → "altar consecrated, used for #pray"

Free-form append-only logs leak tokens and confuse the agent. Keyed
overwrites let the agent maintain a compact, *current* world model. The
key normalization (lowercase, stripped) is permissive: the model can write
`add_note("Altar", ...)` and later `recall("altar")` and they collide.

## Why substring `recall` and not a vector store?

For v0, journal volume is tiny — a typical rollout has 20–50 notes. Substring
match is fast, deterministic, and works without a model dep. The interface
(`recall(query) -> list[(key, text)]`) is forward-compatible: when journal
volume grows or note semantics get fuzzy, swap the impl behind the same
signature.

The upgrade path Alex's RLM work points at: `recall(query)` becomes a sub-LM
call that takes the journal *plus the last K observations* and returns a
synthesis. Same skill, different backend. Token-efficient retrieval over a
growing memory.

## Edge cases handled

- **Empty key** (`add_note("   ", "...")`) → refused with feedback, no state
  change. The model occasionally hallucinates whitespace-only slugs; we don't
  want to silently store junk.
- **Empty query** (`recall("")`) → returns all notes. This is sometimes what
  the model wants (dump the whole memory back).
- **Case insensitivity.** Both key normalization and recall matching are
  case-insensitive. `add_note("DRAGON", ...)` is recallable as
  `recall("dragon")`.
- **Render gating.** `is_empty()` returns True iff there's no objective AND
  no notes; the obs renderer uses this to suppress the empty `=== JOURNAL
  ===` block in early-game turns.

## How to verify

```bash
uv run pytest tests/test_journal.py -v
```

10 tests cover the API (add/recall/pin), the corner cases (empty key, no
match, empty query), and the render block composition.

## Future work

- **Sub-LM recall** (Track B from the project plan): `recall(query)` becomes
  a routed call to a smaller model that summarizes matching notes plus the
  last K observation steps.
- **Auto-summarize at chapter boundaries.** When max_dlvl_reached increases,
  fire an automatic `add_note("dlvl_<n-1>_summary", <auto>)` so the agent
  carries a compressed memory across floors.
- **Token budget.** Cap journal size at e.g. 30 notes or 2000 chars; evict
  LRU on overflow. Today the model can self-manage but high-volume runs
  should have a backstop.
- **Persistence.** Currently in-memory per rollout. If we ever want
  cross-rollout learning (the model accumulates knowledge across episodes),
  serialize journal to disk keyed by character.
