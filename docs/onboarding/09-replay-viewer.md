# Replay viewer: the Monday demo artifact

**Status:** Shipped in `tools/replay_viewer.html` + `nethack_core/replay.py`
frame capture as of Day 3. Tested in `tests/test_replay.py`.

## Why this exists

Pokemon-bench got cultural traction because anyone could watch a stream.
The replay viewer is our version: a self-contained HTML file that opens
any Trajectory JSON and renders the rollout as a scrubbable timeline.

Practical uses:

- **Demo for the Monday review with Alex.** Open a recorded run, scrub
  through it, point at the journal block changing on each step.
- **Debugging.** When `audit_reproducibility` finds a divergence, the
  viewer is how you stare at the two trajectories and figure out which
  step disagrees.
- **Stream / share.** A single .html + a single .json. No server. Drop
  both in a gist; teammates open it in any browser.
- **Annotation substrate.** When we want to label trajectories for Motif-
  style reward learning, this is where the human annotator lives.

## The pieces

```
nethack_core/replay.py         Trajectory, TrajectoryFrame, TrajectoryRecorder
tools/replay_viewer.html       Single-file HTML+JS viewer
```

### Trajectory schema

The recorded JSON has this shape:

```json
{
  "seeds": [42, 42],
  "task_name": "NetHackScore-v0",
  "character": {"role": "monk", "race": "human", ...},
  "actions": [1, 2, 1, 3, ...],
  "rewards": [0.0, 0.0, ...],
  "terminated": false,
  "truncated": false,
  "final_status": {...},
  "frames": [
    {
      "tty": "  ----------- ...\n  |....@... ...",   // 24 rows, newline-joined
      "message": "It's a wall.",
      "status": {"hitpoints": 14, "depth": 1, ...},
      "inventory": [{"letter": "a", "description": "...", "is_worn": false, ...}],
      "reward": 0.0,
      "action": 1,
      "skill": {"name": "autoexplore", "args": {"max_steps": 8}},
      "journal": {"objective": "...", "notes": {...}}
    },
    ...
  ]
}
```

Frame zero is the post-reset state (`action=None`). Frame N is the state
*after* applying action N-1. The viewer treats them uniformly — scrubbing
from 0 to len-1 walks through the rollout.

### Frame capture

`TrajectoryRecorder.step(action, skill=None, journal=None)` builds a
`TrajectoryFrame` from the post-step observation. Disable with
`capture_frames=False` if you're recording at high volume and don't need
the rendering (e.g., audit-only runs).

Cost: ~2 KB / frame. A 500-step rollout is ~1 MB. Fine for the Hub, fine
for git annexed datasets.

### Viewer UI

Three columns of state:

1. **Map** (left, monospace): the rendered tty for the current frame.
   Menus and inventory prompts show inline in the tty exactly as the agent
   saw them.
2. **Right rail**: status (HP, AC, dlvl, ...), last message, inventory list,
   journal state, current step's skill call, and the reward for this step.
3. **Bottom timeline**: scrub bar with first/prev/play/next/last buttons
   and a `frame N / M` counter. Keyboard shortcuts: ← / → for prev/next,
   Space for play/pause, Home / End for first/last.

Play mode auto-advances at 250ms/frame. Configurable in the source.

### URL loading

```
file:///path/to/replay_viewer.html?trajectory=path/to/trajectory.json
```

The viewer fetches the JSON from the relative URL on load. Great for
hosting in CI artifacts or static gist pages.

## How to record a trajectory end-to-end

```bash
source .venv/bin/activate
python -c "
from nethack_core.env import NetHackCoreEnv
from nethack_core.replay import TrajectoryRecorder
from nethack_core.skills import bootstrap_character, autoexplore

env = NetHackCoreEnv(task_name='NetHackScore-v0')
rec = TrajectoryRecorder(env)
rec.reset(seeds=(42, 42))
character = bootstrap_character(env)

for _ in range(5):
    r = autoexplore(env, None, max_steps=8)
    if not r.actions:
        break
    for a in r.actions:
        rec.step(a, skill={'name': 'autoexplore', 'args': {'max_steps': 8}})

traj = rec.export(final_status={'note': 'demo'}, character=character)
traj.save('/tmp/my_trajectory.json')
print(f'Saved {len(traj.frames)} frames')
"
```

Then open the viewer:

```bash
open tools/replay_viewer.html
# Click "Choose File" and pick /tmp/my_trajectory.json
```

Or with URL loading:

```bash
cp /tmp/my_trajectory.json tools/
open "tools/replay_viewer.html?trajectory=my_trajectory.json"
```

## What we deliberately *don't* do (yet)

- **Side-by-side diff mode.** Two trajectories opened simultaneously, with
  the diverging step highlighted. Useful for reproducibility debugging.
  Future work.
- **Color in the tty.** NetHack uses 8-color terminal; we only render
  white-on-dark. Adding `tty_colors` to frames would let the viewer
  render the full colored display.
- **Token / reward overlay.** When we have model logprobs and per-step
  rubric breakdowns, overlay them on the timeline as a sparkline.
- **Streaming.** Currently a frame is captured per `step()`. For very long
  rollouts (1000+ steps) we may want to subsample or use a compact tty
  diff format.

## How to verify

```bash
uv run pytest tests/test_replay.py -v
```

Six tests cover serialization (round-trip, legacy schema), live recording
(capture-on, capture-off), and the replay+audit loop.

Live test:

```bash
source .venv/bin/activate
python -m pip install --quiet ipython  # optional
# record a trajectory as shown above, then open in browser
```

## Future work

- **Hub upload pipeline.** A `prime env push --include-trajectories` flag
  that ships a sample rollout alongside the env so anyone browsing the Hub
  sees a working replay link immediately.
- **Inline analytics.** Sparkline of cumulative reward over the trajectory;
  a tag for the step where each milestone fired; a death-cause highlight
  on the final frame.
- **Differential replay.** Two trajectories side-by-side, scrubbing in
  lockstep, with diverging steps flagged.
- **Annotation export.** Click-and-drag to select a span; mark as "good
  decision" / "bad decision"; export as a labeling dataset.
