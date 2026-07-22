"""Export recorded agent trials to static JSON for the browser Replays page.

The GitHub Pages bundle (`deploy/wasm-web/`) has no server, so the Tracer's
`/traces` + `/trace?path=` endpoints are replaced by flat JSON written ahead of
time by this script:

    trials/index.json    [{id, agent, seed, outcome, max_dlvl, turns}, ...]
    trials/<id>.json     {meta: {...}, turns: [<normalized turn>, ...]}

Two agent architectures are in the corpus and they record different things, so a
turn is normalized to one of two `kind`s:

  ``grid``   (rlm / code-mode) — a tty map snapshot, the code the agent generated
             that step, and the exact text the LLM was shown.
  ``skill``  (voyager) — one skill-library iteration: the objective it wrote, the
             macro it composed, and the per-primitive feedback. No map is recorded.

Run:
    python tools/export_trials.py --root <dir-of-run-dirs> [--out deploy/wasm-web/trials]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rollout_view.index import discover_runs  # noqa: E402

# Run dirs are named `<agent>_seed<N>_<OK|FAIL>_dlvl<D>`; the label is the source
# of truth for the gallery, but it is cross-checked against the trace below so a
# mislabeled directory fails the export instead of quietly misreporting a result.
_NAME_RE = re.compile(r"^(?P<agent>[a-z0-9]+)_seed(?P<seed>\d+)"
                      r"(?:_(?P<outcome>OK|FAIL))?(?:_dlvl(?P<dlvl>\d+))?$")


def _turns(run_dir: Path) -> list:
    """Every JSON record in the run dir's *.ndjson files, in file+line order."""
    out = []
    for f in sorted(run_dir.glob("*.ndjson")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _norm_turn(rec: dict, i: int) -> dict:
    """One raw trace record → the shape `replays.js` renders."""
    if "raw_grid" in rec:
        grid = rec["raw_grid"]
        # Recorded as one blob here, but colorize() (console.js) wants lines.
        rows = grid.splitlines() if isinstance(grid, str) else list(grid)
        pos = rec.get("pos") or []
        return {
            "kind": "grid",
            "turn": rec.get("turn", i),
            "dlvl": rec.get("dlvl"),
            "pos": pos,
            "rows": rows,
            "actions": rec.get("actions_applied"),
            "code": rec.get("code_blocks") or [],
            "user": rec.get("rendered_user_content") or rec.get("rendered_user_message") or "",
            "done": bool(rec.get("done")),
        }
    return {
        "kind": "skill",
        "turn": rec.get("iteration", i),
        "dlvl": rec.get("dlvl"),
        "skill": rec.get("skill_name") or "",
        "objective": rec.get("objective") or "",
        "macro": rec.get("macro") or [],
        "feedback": rec.get("feedback") or [],
        "success": bool(rec.get("success")),
        "stored": bool(rec.get("stored")),
        "library": rec.get("library_size"),
        "done": bool(rec.get("terminated")),
    }


def _max_dlvl(turns: list, recs: list) -> int:
    vals = [t["dlvl"] for t in turns if isinstance(t.get("dlvl"), int)]
    vals += [r["max_dlvl"] for r in recs if isinstance(r.get("max_dlvl"), int)]
    return max(vals) if vals else 1


def _parse_only(spec):
    """--only value -> a set of run-dir names to keep, or None for "all"."""
    if not spec:
        return None
    if spec.startswith("@"):
        text = Path(spec[1:]).read_text()
        names = [ln.split("#", 1)[0].strip() for ln in text.splitlines()]
    else:
        names = spec.split(",")
    keep = {n.strip() for n in names if n.strip()}
    return keep or None


def export(root: Path, out: Path, keep=None) -> list:
    run_dirs = discover_runs(root)
    if not run_dirs:
        raise SystemExit(f"no *.ndjson run directories under {root}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if keep is not None:
        names = {d.name for d in run_dirs}
        missing = keep - names
        if missing:
            raise SystemExit(f"--only names not found under {root}: {sorted(missing)}")
        run_dirs = [d for d in run_dirs if d.name in keep]

    index = []
    for d in sorted(run_dirs, key=lambda p: p.name):
        m = _NAME_RE.match(d.name)
        if not m:
            raise SystemExit(f"run dir {d.name!r} does not match <agent>_seed<N>[_OK|_FAIL][_dlvlD]")
        recs = _turns(d)
        if not recs:
            print(f"  skip {d.name}: no records", file=sys.stderr)
            continue
        turns = [_norm_turn(r, i) for i, r in enumerate(recs)]
        max_dlvl = _max_dlvl(turns, recs)

        labelled = int(m.group("dlvl")) if m.group("dlvl") else max_dlvl
        if labelled != max_dlvl:
            raise SystemExit(f"{d.name}: label says dlvl{labelled} but the trace reaches {max_dlvl}")
        outcome = m.group("outcome") or ("OK" if max_dlvl > 1 else "FAIL")

        meta = {
            "id": d.name,
            "agent": m.group("agent"),
            "seed": int(m.group("seed")),
            "outcome": outcome,
            "max_dlvl": max_dlvl,
            "turns": len(turns),
            "kind": turns[0]["kind"],
            "variant": recs[0].get("variant"),
            "backend": recs[0].get("backend"),
        }
        (out / f"{d.name}.json").write_text(json.dumps({"meta": meta, "turns": turns}))
        index.append(meta)

    (out / "index.json").write_text(json.dumps(index, indent=1))
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, type=Path,
                    help="directory containing one sub-directory per trial")
    ap.add_argument("--out", type=Path, default=Path("deploy/wasm-web/trials"),
                    help="output directory (default: deploy/wasm-web/trials)")
    ap.add_argument("--only",
                    help="export just these trials: a comma-separated list of run-dir "
                         "names, or @path to read one name per line (blank lines and "
                         "# comments ignored). See the output dir's README.md.")
    a = ap.parse_args(argv)
    keep = _parse_only(a.only)
    index = export(a.root.resolve(), a.out.resolve(), keep)
    total = sum((a.out / f"{m['id']}.json").stat().st_size for m in index)
    print(f"wrote {len(index)} trials + index.json to {a.out} ({total / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
