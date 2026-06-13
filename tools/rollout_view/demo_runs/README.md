# Demo descent runs (keyless)

Three skill-driven descent traces for the rollout viewers, generated with no
model/API cost by driving the `explore_and_descend` skill from a fixed seed:

| run | descent (Dlvl) |
|-----|----------------|
| `B1_seed2`  | 1 → 6 |
| `B1_seed19` | 1 → 4 |
| `B1_seed9`  | 1 → 3 |

## View
    PYTHONPATH="$PWD:$PWD/environments/nethack" \
      python -m tools.rollout_view.live_server \
      --runs-root tools/rollout_view/demo_runs --port 8765
    # open http://127.0.0.1:8765  → pick a run → scrub the turns (left: map, right: B1 encoding)

## Regenerate / make new ones
    PYTHONPATH="$PWD:$PWD/environments/nethack" \
      python -m tools.rollout_view.gen_web_play B1 2 14     # variant seed turns
    PYTHONPATH="$PWD:$PWD/environments/nethack" \
      python -m tools.rollout_view.gen_web_play scan        # scan seeds for deep descents
