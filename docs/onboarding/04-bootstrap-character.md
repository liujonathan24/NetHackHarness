# `bootstrap_character`: role/race/align from the welcome line, no extra turn

**Status:** Wired up in `nethack_core/skills.py` as of Day 2. Tested in
`tests/test_skills.py`.

## The need

Every NetHack episode starts with a randomly-(or character-string-)assigned
role, race, alignment, and gender. The same dungeon plays very differently as
a Valkyrie (strong melee, easy ascensions) vs a Wizard (fragile, magic-heavy)
vs a Tourist (notoriously hard). The agent needs this info from turn 1 —
otherwise it has to infer "am I a fighter or a caster?" from the stats line,
which is a waste of context tokens and prone to error.

The ICLR 2026 blogpost validated this: surfacing role/race/align in the
observation improves Sample Factory PPO on MiniHack. We want the same fix.

## What v0 had

`skills.py::bootstrap_character` returned a constant unknown sentinel:

```python
def bootstrap_character(env) -> dict[str, str]:
    return {"role": "unknown", "race": "unknown",
            "alignment": "unknown", "gender": "unknown"}
```

So `format_observation_as_chat` rendered:

```
Character: unknown (unknown, unknown)
```

…on every turn of every episode.

## The fix

Parse the welcome message. NetHack's `env.reset()` always emits something
like:

```
Hello Agent, welcome to NetHack!  You are a neutral male human Monk.
```

…with an optional title prefix for some roles:

```
Hello Agent, the Stripling, welcome to NetHack!  You are a lawful female human Valkyrie.
```

A regex pulls the four fields out:

```python
_WELCOME_RE = re.compile(
    r"You are (?:a |an )?"
    r"(?P<alignment>lawful|neutral|chaotic)\s+"
    r"(?P<gender>male|female|neuter)\s+"
    r"(?P<race>\w+)\s+"
    r"(?P<role>\w+)"
)
```

`bootstrap_character` reads the env's `last_observation`, decodes the message
bytes, runs the regex, returns the dict. Lowercased for consistency with the
rest of the obs schema.

## Why not `#attributes` (the design doc's original plan)?

The design doc proposed sending the in-game `#attributes` command on reset,
parsing the resulting menu. Two problems:

1. **The action set doesn't include `Command.ATTRIBUTES`.** NetHackScore (our
   substrate; see `01-seeding-and-nethackscore.md`) restricts the action set
   to 23 actions for a good reason (smaller decision space → easier RL). To
   send `#attributes` we'd either have to extend our action set (breaking
   parity with PufferLib's NetHack action vocabulary) or build a special
   bootstrap-only env. Neither is great.
2. **It costs a turn.** Sending `#attributes` advances the game turn counter
   and adds entropy to the trajectory. We'd have to either reset the turn
   counter (breaking determinism) or accept a 1-turn handicap on every
   episode.

Parsing the welcome message is one regex on existing data. No extra turn,
no action-set extension, works on every NLE task class.

## Defensive behavior

`bootstrap_character` returns the `unknown` sentinel rather than raising
when:

- The welcome message is missing (e.g., env was stepped before bootstrap).
- The regex fails (NetHack output format changes someday).
- `last_observation` lookup fails for any reason.

This is deliberate: the rest of the system runs fine without character info,
just with a slightly worse system prompt. The wrong response to "we don't
know the role" is *not* to crash the rollout.

## How to verify

End-to-end:

```bash
source .venv/bin/activate
python -c "
from nethack_core.env import NetHackCoreEnv
from nethack_core.skills import bootstrap_character
env = NetHackCoreEnv(task_name='NetHackScore-v0')
env.seed(core=42, disp=42); env.reset()
print(bootstrap_character(env))
"
# -> {'alignment': 'neutral', 'gender': 'male', 'race': 'human', 'role': 'monk'}
```

Tests:

```bash
uv run pytest tests/test_skills.py -v
```

Five tests cover the regex variants (with/without title prefix), the unknown
fallback, and the end-to-end live-NLE bootstrap including determinism under
the same seed.

## Future work

- **Diverse character sampling.** Once curriculum.py wants specific roles,
  we'll pass `character="val-dwa-fem-law"` through to NLE's character
  string. The bootstrap parse still works on whatever the env settles on.
- **Detect role-conditioned starting inventory.** Each role has a known
  starting kit (Valkyrie: long sword + small shield; Monk: martial arts +
  cloak; etc.). Surface "expected starting inventory diff" in the bootstrap
  to spot anomalies (e.g., player picked up something weird before we
  observed them).
