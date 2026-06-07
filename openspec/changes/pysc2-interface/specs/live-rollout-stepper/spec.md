## ADDED Requirements

### Requirement: Step a model rollout live

The harness SHALL provide an interactive driver that runs a chosen model with a
chosen variant/prompt and steps through the rollout one turn at a time. At each
step it SHALL surface the observation the model received (its exact input) and
the action the model took, and SHALL let the user advance (step), pause, and
inspect. It SHALL drive the existing harness rollout path (the env_response loop
+ the variant's rendering) rather than reimplementing rollout logic.

#### Scenario: Step through a rollout turn-by-turn
- **WHEN** the user starts a live rollout with a model + variant and advances one step
- **THEN** it runs exactly one turn and shows the observation the model received and the action it took

#### Scenario: Variant/prompt is selectable
- **WHEN** the user starts a live rollout
- **THEN** they can choose which variant/prompt is used (e.g. B1 / IMG / JSON / TOON), and the observation shown reflects that encoding

#### Scenario: Reuses the harness rollout path
- **WHEN** the stepper advances a turn
- **THEN** it uses the existing env_response rollout path (no forked rollout logic)
