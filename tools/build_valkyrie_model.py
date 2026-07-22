"""Fit the Valkyrie-by-depth stat model from the NLE human dataset (NLD).

Pipeline:
  1. Index an `altorg` (alt.org / NLD-NAO) directory with the vendored NLE
     dataset loader (``add_altorg_directory`` -> ``ttyrecs.db``).
  2. Stream each game's ttyrec frames via ``TtyrecDataset``; keep games whose
     early frames identify a Valkyrie.
  3. Parse the bottom status line of each frame (``nld_parse.parse_status``) to
     recover (depth, XP level, HP/maxHP, attributes).
  4. Aggregate per absolute-depth band and fit a (mean, std) per stat.
  5. Write the artifact JSON consumed by ``ValkyrieUpgradeModel.from_artifact``.

The artifact format::

    {"role": "Valkyrie", "n_games": N, "by_depth": {"48": {"max_hp": {"mean":..,
     "std":..}, "xp_level": {...}, "str": {...}, ...}, ...}}

Usage::

    python tools/build_valkyrie_model.py --altorg /path/to/altorg \
        --out environments/nethack/nethack_core/data/valkyrie_model.json \
        --depths 44 45 46 47 48 49 50

Acquisition: the `altorg` corpus is the alt.org public ttyrec archive (== the
NLD-NAO human dataset). Download per-player ttyrec dirs from alt.org/nethack (or
the NLD release) into one `altorg/` directory with the xlogfile(s), then run this.
Until the artifact exists the curriculum uses the analytic fallback.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
from collections import defaultdict

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "third_party" / "NetHack" / "src"))

from nethack_core import STAT_FIELDS  # noqa: E402
from nethack_core import is_valkyrie, nld_parse  # noqa: E402


def _frame_text(chars) -> str:
    """Render a ttyrec frame's char grid to text (rows joined by newlines)."""
    rows = []
    for row in chars:
        rows.append("".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in row))
    return "\n".join(rows)


def fit(altorg: str, depths: list[int], dbname: str = "nld_valkyrie.db",
        max_games: int = 0) -> dict:
    """Index altorg, stream Valkyrie frames, and fit per-depth stat dists."""
    try:
        import nle.dataset as nld  # vendored loader (needs nle + _pyconverter)
    except ImportError as exc:
        raise SystemExit(
            "NLE dataset loader unavailable: " + str(exc) + "\n"
            "The nle migration removed the installed `nle` package, so the\n"
            "ttyrec decoder (_pyconverter) isn't importable. To run the real\n"
            "fit either (a) build/install the vendored loader at\n"
            "third_party/NetHack/src/nle (with its _pyconverter extension), or\n"
            "(b) decode ttyrecs with a standalone reader + a Python VT emulator\n"
            "(e.g. pyte) and feed each frame to nethack_core.nld_parse.\n"
            "Until then the curriculum uses the analytic fallback "
            "(ValkyrieUpgradeModel.analytic())."
        )

    if not nld.db.exists(dbname):
        nld.db.create(dbname)
        nld.populate_db.add_altorg_directory(altorg, "nld-nao", dbname)

    data = nld.TtyrecDataset("nld-nao", batch_size=1, seq_length=32, dbname=dbname)
    # depth -> stat -> list of values
    samples: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    n_games = 0
    seen_games: set = set()
    for batch in data:
        chars = batch["tty_chars"]  # (batch, seq, rows, cols)
        gameids = batch.get("gameids")
        b, s = chars.shape[0], chars.shape[1]
        for bi in range(b):
            gid = int(gameids[bi][0]) if gameids is not None else bi
            valk = None
            for si in range(s):
                text = _frame_text(chars[bi, si])
                if valk is None:
                    valk = is_valkyrie(text)
                if not valk:
                    break
                st = nld_parse.parse_status(text)
                if not st or st["depth"] not in depths:
                    continue
                if gid not in seen_games:
                    seen_games.add(gid)
                    n_games += 1
                for f in STAT_FIELDS:
                    if f in st:
                        samples[st["depth"]][f].append(st[f])
        if max_games and n_games >= max_games:
            break

    by_depth = {}
    for depth, stats in samples.items():
        band = {}
        for f, vals in stats.items():
            if not vals:
                continue
            mean = statistics.fmean(vals)
            std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            band[f] = {"mean": round(mean, 2), "std": round(std, 2), "n": len(vals)}
        if band:
            by_depth[str(depth)] = band
    return {"role": "Valkyrie", "n_games": n_games, "by_depth": by_depth}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--altorg", required=True, help="path to the altorg/ dataset dir")
    ap.add_argument("--out", required=True, help="artifact JSON output path")
    ap.add_argument("--depths", type=int, nargs="+",
                    default=[44, 45, 46, 47, 48, 49, 50])
    ap.add_argument("--db", default="nld_valkyrie.db")
    ap.add_argument("--max-games", type=int, default=0)
    args = ap.parse_args()

    artifact = fit(args.altorg, args.depths, dbname=args.db, max_games=args.max_games)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2))
    print(f"wrote {out}: {artifact['n_games']} Valkyrie games, "
          f"depths {sorted(artifact['by_depth'])}")


if __name__ == "__main__":
    main()
