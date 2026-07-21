"""Generate demo rollout runs (keyless, scripted) so the viewer has traces to show.

Drives a `NetHackInterface` via the `LiveStepper` with a fixed scripted action
sequence (autoexplore / search / moves) and dumps each turn to an NDJSON trace in
the `REPLAY_LOG_KEYS` format under `<out_root>/demo_<variant>_<seed>/`. For image
encodings (IMG / IMG_TTY) the per-turn image data-URI is written to `images/` and
referenced by path (via the encoding-eval capture helper), so the demo run renders
real images in the HTML viewer. No model calls, no API cost.

Run:  PYTHONPATH=repo:repo/environments/nethack python -m tools.rollout_view.demo
"""
from __future__ import annotations

import json
from pathlib import Path


def _scripted_actions(n: int):
    """A small repeating action script that produces visible map movement."""
    from nethack_interface import Action
    base = [
        Action("autoexplore", {"max_steps": 20}),
        Action("search", {}),
        Action("move", {"direction": "E"}),
        Action("autoexplore", {"max_steps": 20}),
        Action("move", {"direction": "S"}),
    ]
    return [base[i % len(base)] for i in range(n)]


def generate_demo_run(variant: str, *, steps: int = 8, seed: int = 7,
                      out_root="environments/nethack/outputs/evals") -> Path:
    from nethack_core import NetHackCoreEnv
    from nethack_interface import NetHackInterface
    from nethack_harness.helpers import _capture_user_content
    from tools.rollout_view.live_server import LiveStepper

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=seed, disp=seed)
    stepper = LiveStepper(NetHackInterface(env), variant=variant)

    run_dir = Path(out_root) / f"demo_{variant}_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{variant}_{seed}"

    for action in _scripted_actions(steps):
        try:
            stepper.step_once(action)
        except Exception:
            break  # a skill may interrupt (menu/death); keep what we have

    # Dump history → NDJSON, rewriting image data-URIs to on-disk PNG refs.
    lines = []
    for t in stepper.history:
        content = t.get("rendered_user_content")
        content = _capture_user_content(content, run_dir, run_id=run_id, turn=t["turn"])
        lines.append(json.dumps({**t, "rendered_user_content": content, "variant": variant}))
    (run_dir / f"{run_id}.ndjson").write_text("\n".join(lines))
    return run_dir


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Generate demo rollout traces for the viewer.")
    p.add_argument("--variants", nargs="+", default=["B1", "JSON", "IMG"])
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--out-root", default="environments/nethack/outputs/evals")
    args = p.parse_args(argv)
    for v in args.variants:
        d = generate_demo_run(v, steps=args.steps, out_root=args.out_root)
        n = len((d / f"{v}_7.ndjson").read_text().splitlines())
        print(f"  {v:8s} -> {d}  ({n} turns)")


if __name__ == "__main__":  # pragma: no cover
    main()
