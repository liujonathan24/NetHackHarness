"""Collect wave-2 hosted evals and emit a descent-rate comparison.

Pulls every running/completed eval whose name matches `wave1-{variant}-...`,
groups by variant, downloads samples via `prime eval samples --output json`,
and feeds the two collections into `tools.eval_instrument.comparison_table`.

Usage:
    python experiments/wave2_collect.py --a N --b E1 --wait

The --wait flag polls until every job is COMPLETED (or FAILED) before
collecting.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

OUT_DIR = Path("experiments/results/wave2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

_NAME_RE = re.compile(r"wave1-([A-Z0-9]+)-.+-seed(\d+)$")


def _prime_json(args: list[str]) -> dict:
    out = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def list_evals_for_variant(variant: str, since_date: str | None = None) -> list[dict]:
    """List COMPLETED evals matching wave1-<variant>-...-seed<N>, latest per seed."""
    rows: list[dict] = []
    page = 1
    while True:
        data = _prime_json(["prime", "--plain", "eval", "list", "--page", str(page),
                            "--num", "100", "--output", "json"])
        page_rows = data.get("evaluations") or data.get("items") or []
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 100:
            break
        page += 1
    by_seed: dict[int, dict] = {}
    for r in rows:
        name = r.get("eval_name") or r.get("name") or ""
        m = _NAME_RE.match(name)
        if not m or m.group(1) != variant:
            continue
        if (r.get("status") or "").upper() != "COMPLETED":
            continue
        created = r.get("created_at") or ""
        if since_date and created[:10] < since_date:
            continue
        seed = int(m.group(2))
        prev = by_seed.get(seed)
        if prev is None or (created > (prev.get("created_at") or "")):
            r["_seed"] = seed
            r["_variant"] = variant
            by_seed[seed] = r
    return sorted(by_seed.values(), key=lambda r: r["_seed"])


def wait_for_completion(eval_ids: list[str], poll_s: int = 30, max_wait_s: int = 7200) -> None:
    start = time.time()
    while True:
        statuses: dict[str, str] = {}
        for eid in eval_ids:
            try:
                d = _prime_json(["prime", "--plain", "eval", "get", eid, "--output", "json"])
                statuses[eid] = (d.get("status") or "?").upper()
            except subprocess.CalledProcessError:
                statuses[eid] = "ERR"
        pending = [k for k, v in statuses.items() if v in ("RUNNING", "QUEUED", "PENDING", "?", "ERR")]
        if not pending:
            return
        if time.time() - start > max_wait_s:
            print(f"[timeout] still pending: {pending}", file=sys.stderr)
            return
        done = len(eval_ids) - len(pending)
        print(f"[wait] {done}/{len(eval_ids)} done; sleeping {poll_s}s", file=sys.stderr)
        time.sleep(poll_s)


def fetch_samples(eval_id: str, dest: Path) -> dict:
    d = _prime_json(["prime", "--plain", "eval", "samples", eval_id, "--num", "100", "--output", "json"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(d))
    return d


def collect_variant(variant: str, wait: bool, since_date: str | None) -> Path:
    evals = list_evals_for_variant(variant, since_date=since_date)
    if not evals:
        print(f"[err] no evals found for variant {variant}", file=sys.stderr)
        sys.exit(2)
    eval_ids = [e.get("id") or e.get("evaluation_id") for e in evals]
    print(f"[{variant}] {len(eval_ids)} evals: {eval_ids}", file=sys.stderr)
    if wait:
        wait_for_completion(eval_ids)
    # Combine into a single hosted-style dump consumable by eval_instrument.
    combined = {"samples": [], "evaluation_ids": eval_ids}
    for eid, meta in zip(eval_ids, evals):
        seed = meta.get("_seed")
        per_file = OUT_DIR / f"{variant}_seed{seed}_{eid}.json"
        d = fetch_samples(eid, per_file)
        for s in (d.get("samples") or []):
            s["_seed"] = seed
            s["_eval_id"] = eid
            # eval_instrument reads `seed` first, falls back to example_id.
            s.setdefault("seed", seed)
            combined["samples"].append(s)
    out = OUT_DIR / f"{variant}_combined.json"
    out.write_text(json.dumps(combined))
    print(f"[{variant}] wrote {out} ({len(combined['samples'])} samples)", file=sys.stderr)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--a", default="N", help="Variant A (control). Default N.")
    p.add_argument("--b", default="E1", help="Variant B (treatment). Default E1.")
    p.add_argument("--wait", action="store_true", help="Poll until all jobs finish.")
    p.add_argument("--since", default=None,
                   help="Only include evals created on/after YYYY-MM-DD. "
                        "Use this to scope a sweep when older runs share the tag.")
    args = p.parse_args()

    path_a = collect_variant(args.a, args.wait, args.since)
    path_b = collect_variant(args.b, args.wait, args.since)

    from tools.eval_instrument import load_hosted_eval_samples, comparison_table
    sa = load_hosted_eval_samples(path_a)
    sb = load_hosted_eval_samples(path_b)
    md = comparison_table(args.a, sa, args.b, sb)
    out_md = OUT_DIR / f"compare_{args.a}_vs_{args.b}.md"
    out_md.write_text(md)
    print(md)
    print(f"\n[wrote] {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
