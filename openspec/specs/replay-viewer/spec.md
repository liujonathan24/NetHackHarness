## ADDED Requirements

### Requirement: Rich rollout replay viewer

The harness SHALL provide a rich replay viewer that reads a recorded rollout via
the documented encoding-eval seam (`REPLAY_LOG_KEYS` + the per-turn NDJSON trace
with `rendered_user_content` + the `images/` directory) and renders it in two
forms: a human-viewable game-state timeline and the exact LLM-input form per
turn. For image encodings (IMG / IMG_TTY) the LLM-input form SHALL display the
actual captured image (from the referenced PNG) — not a text elision — via a
self-contained HTML replay export. The viewer SHALL read the same on-disk format
the encoding-eval minimal renderer documented (no new capture format).

#### Scenario: Renders the human-viewable timeline
- **WHEN** a recorded rollout is opened in human-viewable mode
- **THEN** it shows the game-state timeline (per-turn map/tty + message) across turns

#### Scenario: Renders the exact LLM-input form with images
- **WHEN** a rollout that used an image encoding is opened in LLM-input mode
- **THEN** each turn shows the text the model received and the actual captured image inline (HTML export), not a text-only elision

#### Scenario: Reads the documented seam without re-capture
- **WHEN** the viewer loads a run directory produced by the encoding-eval harness
- **THEN** it consumes the `REPLAY_LOG_KEYS` trace fields + `images/` directory directly, requiring no changes to how rollouts are captured

#### Scenario: Launchpad integration
- **WHEN** the user opens a recorded run in the launchpad TUI
- **THEN** the TUI shows the text forms and offers to open the self-contained HTML replay for full image fidelity
