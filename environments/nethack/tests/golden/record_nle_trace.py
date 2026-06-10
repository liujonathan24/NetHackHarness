"""Record a golden nle trace (seed 42/42) as a parity oracle for the custom
_engine binding. Run with the project venv:
    cd environments/nethack && ../../.venv/bin/python tests/golden/record_nle_trace.py
Regeneration requires `nle` installed (removed in a later cutover task), so the
generated .npz is committed.

Frame indexing contract:
  frame 0  = post-reset initial observation (before any action)
  frame i+1 = observation after applying actions[i]

This lets the parity test check setup alignment (frame 0) independently of
per-action parity (frames 1..N).
"""
import os
import numpy as np
from nle import nethack

SEED_CORE = 42
SEED_DISP = 42
N_STEPS = 200

# Options string must exactly match the fork engine's _OPTIONS_STR so the
# oracle and the binding run with identical nethack option flags.
NETHACKOPTIONS = (
    "autopickup", "color", "disclose:+i +a +v +g +c +o", "mention_walls",
    "nobones", "nocmdassist", "nolegacy", "nosparkle",
    "pickup_burden:unencumbered", "pickup_types:$?!/", "runmode:teleport",
    "showexp", "showscore", "time",
)

# Observation keys to capture (GATE-relevant). ORDER defines the tuple order.
KEYS = ("tty_chars", "tty_colors", "glyphs", "chars", "colors", "blstats", "message")

# Deterministic action stream: safe movement + search (avoids menus). Raw values.
#   h j k l y u b n  = compass; s = search
SAFE_ACTIONS = np.array([104, 106, 107, 108, 121, 117, 98, 110, 115], dtype=np.int64)


def main():
    rng = np.random.RandomState(0)
    actions = rng.choice(SAFE_ACTIONS, size=N_STEPS).astype(np.int64)

    nh = nethack.Nethack(observation_keys=KEYS, playername="Agent-mon-hum-neu-mal",
                         spawn_monsters=True, options=list(NETHACKOPTIONS))
    nh.set_initial_seeds(SEED_CORE, SEED_DISP, False)
    init = nh.reset()
    idx = {k: i for i, k in enumerate(KEYS)}

    # Frame 0 = initial (post-reset). Frames 1..N = post-action.
    frames = {k: [init[idx[k]].copy()] for k in KEYS}
    used_actions = []
    for a in actions:
        obs, done = nh.step(int(a))
        for k in KEYS:
            frames[k].append(obs[idx[k]].copy())
        used_actions.append(int(a))
        if done:
            break
    nh.close()

    out = {k: np.stack(v) for k, v in frames.items()}   # each (n_frames, ...)
    out["actions"] = np.array(used_actions, dtype=np.int64)  # len = n_frames - 1
    out["seeds"] = np.array([SEED_CORE, SEED_DISP], dtype=np.int64)

    path = os.path.join(os.path.dirname(__file__), "trace_score_seed42.npz")
    np.savez_compressed(path, **out)
    print(f"Wrote {path}: {len(used_actions)} steps, frames={out['tty_chars'].shape}")


if __name__ == "__main__":
    main()
