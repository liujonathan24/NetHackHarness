"""Render an animated GIF/MP4 of an LLM-NetHack rollout from per-turn
chat samples.

Two input modes:

  1. Prime-hosted: `--eval-id <id>` fetches via `prime eval samples`
     and reads the per-turn user/assistant messages.
  2. Local NDJSON: `--ndjson <path>` reads the trace_dir file
     env-side TrajectoryRecorder writes (one JSON per turn with
     raw_grid + rendered_user_message + assistant_message).

Output: PNG frames + an animated GIF showing
  - the ASCII map (24x80 tty)
  - the status / hp / dlvl line
  - the tool call the agent issued this turn
  - turn counter

Usage:
    # from a hosted eval:
    python tools/render_rollout_video.py --eval-id <ID> --out videos/N_seed22.gif

    # from a local trace:
    python tools/render_rollout_video.py --ndjson trace.ndjson --out videos/B1_seed24.gif

    # render both variants side by side for direct comparison:
    python tools/render_rollout_video.py --eval-id <N_id> --eval-id <B1_id> \
        --labels "N (NetPlay)" "B1 (default)" --out videos/N_vs_B1.gif

Dependencies: matplotlib (already in repo), Pillow (for GIF assembly,
typically already installed via matplotlib).
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import animation


_MAP_BLOCK = re.compile(r"=== MAP ===\n(.+?)\n\n(?:===|$)", re.DOTALL)
_STATUS_LINE = re.compile(r"=== STATUS ===\n(.+?)$", re.MULTILINE)


def parse_observation(user_msg: str) -> dict:
    """Extract the rendered map + status from a user-message string the env
    writes via format_observation_as_chat()."""
    out = {"map": "", "status": "", "messages": "", "hint": ""}
    m = _MAP_BLOCK.search(user_msg)
    if m:
        out["map"] = m.group(1)
    s = _STATUS_LINE.search(user_msg)
    if s:
        out["status"] = s.group(1).strip()
    if "=== HINT ===" in user_msg:
        hi = re.search(r"=== HINT ===(.+?)(?:\n\n|\Z)", user_msg, re.DOTALL)
        if hi:
            out["hint"] = hi.group(1).strip()
    if "=== MESSAGES ===" in user_msg:
        mb = re.search(r"=== MESSAGES ===\n(.+?)(?:\n\n|\Z)", user_msg, re.DOTALL)
        if mb:
            out["messages"] = mb.group(1).strip()
    return out


def parse_tool_call(assistant_msg) -> str:
    """Extract a one-line tool-call summary from an assistant message dict."""
    if not assistant_msg:
        return "(no action)"
    tc = assistant_msg.get("tool_calls") if isinstance(assistant_msg, dict) else None
    if not tc:
        return "(no tool call)"
    first = tc[0]
    if isinstance(first, dict):
        fn = first.get("function") or {}
        name = fn.get("name") or first.get("name") or "?"
        args = fn.get("arguments") or first.get("arguments") or "{}"
    else:
        name = getattr(first, "name", "?")
        args = getattr(first, "arguments", "{}")
    if isinstance(args, str):
        try:
            args_d = json.loads(args)
        except Exception:
            args_d = {}
    else:
        args_d = args or {}
    args_short = ",".join(f"{k}={v}" for k, v in list(args_d.items())[:3])
    return f"{name}({args_short})"


def load_hosted(eval_id: str) -> list[dict]:
    """Use `prime eval samples` to pull per-rollout sample list. Each
    sample contains the full per-turn messages array under
    `sample['input']` (system + user turns) and `sample['output']`
    (assistant message(s)).

    Returns a list of per-turn frames: {turn, user_msg, assistant_msg}.
    """
    # Paginate. Default per page=100.
    samples = []
    for page in range(1, 20):
        cmd = ["prime", "eval", "samples", eval_id, "--output", "json",
               "--plain", "-p", str(page), "-n", "100"]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"prime eval samples failed: {out.stderr or out.stdout}")
        d = json.loads(out.stdout)
        chunk = d.get("samples") or []
        if not chunk:
            break
        samples.extend(chunk)
        if len(samples) >= int(d.get("total", 0) or 0):
            break
    # Verifiers stores the full message list per sample. We expect 1 sample
    # per rollout (n_examples=1, rollouts_per_example=1) — multi-turn is
    # encoded inside that sample's messages.
    if not samples:
        raise RuntimeError("No samples returned for that eval_id.")
    s = samples[0]
    # Prime/verifiers shape: sample['prompt'] is system+initial user (length 2),
    # sample['completion'] is the alternating list of (assistant, tool, user)
    # messages produced during the rollout.
    msgs = list(s.get("prompt") or []) + list(s.get("completion") or [])
    # Fall back to older shapes if needed.
    if not msgs:
        msgs = (s.get("messages") or s.get("trajectory") or [])
    frames = []
    turn = 0
    last_user = None
    for m in msgs:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "user":
            last_user = content
        elif role == "assistant" and last_user is not None:
            turn += 1
            frames.append({
                "turn": turn,
                "user_msg": last_user,
                "assistant_msg": m,
            })
            last_user = None
    return frames


def load_ndjson(path: Path) -> list[dict]:
    """Read the env-side trace NDJSON written when trace_dir is set."""
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        out.append({
            "turn": d.get("turn", 0),
            "user_msg": d.get("rendered_user_message") or "",
            "assistant_msg": {
                "content": d.get("assistant_message") or "",
                "tool_calls": d.get("tool_calls") or [],
            },
        })
    return out


def render_video(frames_groups: list[list[dict]], labels: list[str],
                 out_path: Path, fps: int = 4):
    """Render one or more rollout streams as a side-by-side animation.

    Each group is a list of per-turn frames; they're padded to the
    max length so the animation runs to completion. ASCII map + status +
    last tool call are drawn per turn.
    """
    n_panels = len(frames_groups)
    max_turns = max(len(g) for g in frames_groups)
    fig, axes = plt.subplots(1, n_panels, figsize=(7 * n_panels, 8))
    if n_panels == 1:
        axes = [axes]

    # Use a monospace font.
    for ax in axes:
        ax.set_axis_off()

    text_artists = []
    for ax, label in zip(axes, labels):
        t = ax.text(0.0, 1.0, "", family="monospace", fontsize=8,
                    verticalalignment="top", transform=ax.transAxes)
        title = ax.text(0.5, 1.02, label, family="monospace",
                        fontsize=11, weight="bold",
                        ha="center", va="bottom",
                        transform=ax.transAxes)
        text_artists.append(t)

    def update(i):
        artists = []
        for idx, (group, text) in enumerate(zip(frames_groups, text_artists)):
            f = group[min(i, len(group) - 1)] if group else None
            if f is None:
                text.set_text("(no frames)")
                continue
            ob = parse_observation(f["user_msg"])
            tc = parse_tool_call(f["assistant_msg"])
            screen = []
            screen.append(f"Turn {f['turn']:3d}   action: {tc}")
            screen.append("-" * 78)
            screen.append(ob["status"] or "(no status)")
            screen.append("")
            screen.append(ob["map"] or "(no map)")
            if ob["hint"]:
                screen.append("")
                screen.append(f"HINT: {ob['hint']}")
            if ob["messages"]:
                screen.append("")
                screen.append("MSGS: " + ob["messages"].replace("\n", " | "))
            text.set_text("\n".join(screen))
            artists.append(text)
        return artists

    anim = animation.FuncAnimation(
        fig, update, frames=max_turns, interval=1000 // max(fps, 1),
        blit=False, repeat=False,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".mp4":
        try:
            anim.save(out_path, writer=animation.FFMpegWriter(fps=fps),
                      dpi=120)
        except Exception as e:
            print(f"[warn] mp4 save failed ({e}); falling back to gif",
                  file=sys.stderr)
            out_path = out_path.with_suffix(".gif")
            anim.save(out_path, writer="pillow", fps=fps)
    else:
        anim.save(out_path, writer="pillow", fps=fps)
    plt.close(fig)
    print(f"wrote {out_path} ({max_turns} frames, {fps}fps)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-id", action="append", default=[],
                    help="Hosted eval ID to fetch via `prime eval samples`. Repeatable.")
    ap.add_argument("--ndjson", action="append", default=[],
                    help="Local NDJSON trace file. Repeatable.")
    ap.add_argument("--samples-json", action="append", default=[],
                    help="Already-fetched `prime eval samples ... -o json` file. Repeatable.")
    ap.add_argument("--labels", nargs="+", default=None,
                    help="Panel labels (one per input source).")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output path (.gif or .mp4).")
    ap.add_argument("--fps", type=int, default=4)
    args = ap.parse_args()

    sources = (
        [("eval", e) for e in args.eval_id]
        + [("ndjson", n) for n in args.ndjson]
        + [("samples_json", j) for j in args.samples_json]
    )
    if not sources:
        ap.error("Pass at least one --eval-id, --ndjson, or --samples-json.")
    groups = []
    auto_labels = []
    for kind, src in sources:
        if kind == "eval":
            frames = load_hosted(src)
            auto_labels.append(f"eval:{src[:8]}")
        elif kind == "ndjson":
            frames = load_ndjson(Path(src))
            auto_labels.append(Path(src).stem)
        else:  # samples_json — already-cached `prime eval samples` output
            d = json.loads(Path(src).read_text())
            s = (d.get("samples") or [None])[0]
            if s is None:
                raise RuntimeError(f"No samples in {src}")
            msgs = list(s.get("prompt") or []) + list(s.get("completion") or [])
            frames = []
            turn = 0
            last_user = None
            for m in msgs:
                role = (m.get("role") or "").lower()
                content = m.get("content") or ""
                if role == "user":
                    last_user = content
                elif role == "assistant" and last_user is not None:
                    turn += 1
                    frames.append({"turn": turn, "user_msg": last_user, "assistant_msg": m})
                    last_user = None
            auto_labels.append(Path(src).stem)
        groups.append(frames)
        print(f"loaded {len(frames)} frames from {kind}:{src}")
    labels = args.labels if args.labels else auto_labels
    if len(labels) != len(groups):
        ap.error("--labels count must match number of input sources.")
    render_video(groups, labels, args.out, fps=args.fps)


if __name__ == "__main__":
    main()
