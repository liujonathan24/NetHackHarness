## High-level approach

This change finishes the migration. The risky pieces (parity, snapshot) are already done and green, so the work is integration + removal, sequenced so the harness never has two live backends at once.

### Decision 1 — `EngineEnv` becomes canonical; don't keep two env classes

Rather than rewrite `NetHackCoreEnv` in place against `import nle`, fold it onto the existing `EngineEnv`. Approach: make `NetHackCoreEnv` delegate to `EngineEnv` (thin adapter preserving the public `seed/reset/step` + observation surface), then delete the nle-backed internals. This keeps `observations.py shape()` and `StructuredObservation` consumers unchanged — parity is asserted by a field/type test against the pre-cutover shape. Action mapping in `skills.py` moves to the engine's keypress action space (already validated identity-ish by GATE A).

### Decision 2 — remove nle only behind the green gates, in one commit

GATE A (structured parity) and determinism already pass. The nle removal (`import nle` deletion + `nle>=1.3.0` drop from pyproject/lock + `Dockerfile.prime`) lands as one reviewable cutover commit, *after* the env/skills/replay swap, so the diff that removes nle is the diff that proves nothing else imports it. A repo-wide `grep -rn "import nle\|from nle\|minihack"` must come back clean (outside archived/legacy docs) as the cutover's acceptance check.

### Decision 3 — level loading: extend the existing tune-at-start plumbing

`nle_load_level` follows the same "set before `mklev`" pattern already used for generation knobs (the starting level is built inside `nle_start`). The fork adds a level-source override to `nle_settings`/`nle_start`; the binding exposes `load_level(...)` on `RawEngine`/`EngineEnv`. The preset/level format (OQ4) is decided here — likely reuse NetHack `des` description files the fork can already parse, bundled as harness assets, so the MiniHack curriculum tiers re-express directly.

### Decision 4 — replay rides on snapshot/restore, not action re-execution

`legacy/replay.py` currently re-executes recorded actions through nle. Swap to: snapshot at episode start (and optionally at checkpoints), restore + step to scrub. The trajectory surface the replay viewer consumes (`replay-viewer` capability) stays the same shape; only the producer changes.

### Decision 5 — generation knobs: settability-first

The remaining Pillar 2 knobs (mob/trap/door/corridor/room_size) mostly affect off-screen/hidden state, so they aren't obs-effect-testable like `room_density` was. Wire each to its `mklev`/spawn read-site, and gate them with settability + smoke tests (no crash, value round-trips, floor still generates) rather than obs-diff assertions. Honestly mark which are visually demoable.

## Sequencing & gates

1. Fork C: `nle_load_level` + remaining knob read-sites → fork PR → bump submodule.
2. Binding: expose `load_level`; harness: env/skills/replay swap onto `EngineEnv`.
3. Cutover: remove nle + minihack; Docker; curriculum re-expressed.
4. Verify: parity/determinism still green, full eval smoke end-to-end, docs.

Hard gates (unchanged from the parent migration): GATE A parity and determinism must stay green across the cutover. Two-repo rule: engine C → fork branch + PR; harness only bumps the submodule pointer.

## Open questions (resolve in deep design / brainstorming)

- OQ4: exact preset/level format and where curriculum assets live.
- Replay back-compat: do existing recorded `.ndjson`/trajectories need a migration, or is replay forward-only from the cutover?
- Curriculum parity: how to confirm re-expressed tiers match the MiniHack originals (golden level dumps? behavioral smoke?).
