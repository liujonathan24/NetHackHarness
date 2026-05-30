"""NetHack eval dashboard — browse hosted eval results + replay rollouts.

A single-file Flask app with two views:

  1. Results overview (/)         — table of all nethack evals (variant,
     model, seed, status, total score) + a per-variant aggregate with the
     four-component reward decomposition (scout / descent / success /
     ascension). CANCELLED/FAILED are shown in the raw list but excluded
     from aggregates.
  2. Rollout replay  (/replay/<eval_id>) — step through a rollout turn by
     turn: ASCII map + status line + the tool call the agent issued, plus
     messages/hint. Reuses the parse_observation / parse_tool_call /
     load_hosted logic from tools/render_rollout_video.py (inlined here so
     the dashboard is self-contained against branch churn).

Data is pulled via the `prime` CLI (team must already be configured) and
cached as JSON under tools/.dashboard_cache/ so page loads don't re-hit the
API. Hit /refresh (or the "Refresh" button) to invalidate the eval-list
cache; per-eval sample caches are keyed by eval id and persist.

Reward schema (avg_score is the UNWEIGHTED SUM of the four components):
    avg_score = scout_reward + descent_reward + success_reward + ascension_reward

Usage:
    # from the repo root
    uv run python tools/dashboard.py            # serves on http://127.0.0.1:5005
    uv run python tools/dashboard.py --port 5005 --no-network   # cache only

Flags:
    --port N        port to bind (default 5005)
    --host H        host to bind (default 127.0.0.1)
    --no-network    never call prime; serve only what's already cached
    --refresh       force a fresh eval-list pull on startup
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from flask import Flask, abort, jsonify, redirect, request, url_for

# --------------------------------------------------------------------------
# Config / paths
# --------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
CACHE_DIR = TOOLS_DIR / ".dashboard_cache"
CACHE_DIR.mkdir(exist_ok=True)
EVAL_LIST_CACHE = CACHE_DIR / "eval_list.json"
SAMPLES_DIR = CACHE_DIR / "samples"
SAMPLES_DIR.mkdir(exist_ok=True)

# How the dashboard invokes the prime CLI. `uv run prime` ensures the
# right venv; falls back to bare `prime` if uv isn't around.
_PRIME_BASE = ["uv", "run", "prime"]

ALLOW_NETWORK = True
REWARD_COMPONENTS = ["scout_reward", "descent_reward", "success_reward", "ascension_reward"]

app = Flask(__name__)


# --------------------------------------------------------------------------
# prime CLI wrapper with retry/backoff (API intermittently 500s / 401s)
# --------------------------------------------------------------------------
def _run_prime(args: list[str], retries: int = 4, timeout: int = 180) -> dict:
    """Run `prime <args> --output json --plain`, parse JSON, retry on flake."""
    cmd = _PRIME_BASE + args + ["--output", "json", "--plain"]
    last_err = ""
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout}s"
            time.sleep(2 * (attempt + 1))
            continue
        out = proc.stdout or ""
        # `uv run` may prepend venv-setup chatter; grab the JSON body.
        body = _extract_json(out)
        if proc.returncode == 0 and body is not None:
            return body
        last_err = (proc.stderr or out or "").strip()[-500:]
        # transient: 500 / unauthorized / rate limit
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"prime {' '.join(args)} failed after {retries} tries: {last_err}")


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first top-level JSON object out of CLI output."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start:i + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


# --------------------------------------------------------------------------
# Data fetching (with cache)
# --------------------------------------------------------------------------
def fetch_eval_list(force: bool = False) -> list[dict]:
    """Paginated `prime eval list -e nethack`. Cached as eval_list.json."""
    if not force and EVAL_LIST_CACHE.exists():
        try:
            return json.loads(EVAL_LIST_CACHE.read_text())
        except json.JSONDecodeError:
            pass
    if not ALLOW_NETWORK:
        return []
    evals: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 21):
        data = _run_prime(["eval", "list", "-e", "nethack", "-n", "100", "-p", str(page)])
        chunk = data.get("evaluations") or []
        if not chunk:
            break
        for e in chunk:
            eid = e.get("evaluation_id") or e.get("id")
            if eid and eid not in seen:
                seen.add(eid)
                evals.append(e)
        total = int(data.get("total") or 0)
        if total and len(seen) >= total:
            break
        if len(chunk) < 100:
            break
    EVAL_LIST_CACHE.write_text(json.dumps(evals, indent=1))
    return evals


def fetch_samples(eval_id: str, force: bool = False) -> dict:
    """Paginated `prime eval samples <id>`. Cached per eval id."""
    cache = SAMPLES_DIR / f"{eval_id}.json"
    if not force and cache.exists():
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            pass
    if not ALLOW_NETWORK:
        return {"samples": []}
    samples: list[dict] = []
    total = 0
    for page in range(1, 21):
        data = _run_prime(["eval", "samples", eval_id, "-p", str(page), "-n", "100"])
        chunk = data.get("samples") or []
        if not chunk:
            break
        samples.extend(chunk)
        total = int(data.get("total") or 0)
        if total and len(samples) >= total:
            break
        if len(chunk) < 100:
            break
    payload = {"evaluation_id": eval_id, "samples": samples, "total": total or len(samples)}
    cache.write_text(json.dumps(payload))
    return payload


# --------------------------------------------------------------------------
# Eval-record normalization
# --------------------------------------------------------------------------
def _derive_variant_seed(e: dict) -> tuple[Optional[str], Optional[int]]:
    """Variant + seed for an eval.

    The eval *name* tag (``wave<N>-<variant>-<model>-seed<S>``) is the
    authoritative experiment label and is preferred. ``env_args.variant`` is
    only the per-turn *formatter* and is NOT a reliable variant id — e.g. the
    NetPlay (N) experiment sets ``variant="B1"`` because its delta is
    ``skill_set`` (no low-level ``move``), so reading ``env_args.variant``
    would mislabel every N run as B1 and corrupt the per-variant aggregate.
    """
    cfg = (e.get("eval_config") or {})
    env_args = cfg.get("env_args") or {}
    name = e.get("name") or ""

    variant = None
    seed = None
    # 1. Authoritative: the run-tag in the eval name.
    m = re.match(r"^wave\d+-([A-Za-z0-9]+)-.*?seed(\d+)$", name)
    if m:
        variant = m.group(1)
        seed = int(m.group(2))
    # 2. Fall back to env_args (formatter id) only when the name has no tag.
    if variant is None:
        variant = env_args.get("variant")
    if seed is None:
        seeds = env_args.get("explicit_seeds")
        if isinstance(seeds, list) and seeds:
            seed = seeds[0]
    if seed is None:
        m2 = re.search(r"seed(\d+)", name)
        if m2:
            seed = int(m2.group(1))
    return variant, seed


def normalize_eval(e: dict) -> dict:
    eid = e.get("evaluation_id") or e.get("id") or ""
    variant, seed = _derive_variant_seed(e)
    return {
        "id": eid,
        "name": e.get("name") or "",
        "model": e.get("model_name") or (e.get("metadata") or {}).get("model") or "?",
        "variant": variant,
        "seed": seed,
        "status": e.get("status") or "?",
        "score": e.get("avg_score"),
        "created_at": e.get("created_at") or "",
        "n_samples": e.get("total_samples") or 0,
    }


def load_records(force: bool = False) -> list[dict]:
    raw = fetch_eval_list(force=force)
    recs = [normalize_eval(e) for e in raw]
    recs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return recs


def aggregate_components(records: list[dict]) -> dict:
    """Per-variant component decomposition, averaged over COMPLETED evals.

    The eval-list rows only carry the summed avg_score, not the per-component
    split. To decompose we pull per-eval samples (cached) for COMPLETED evals
    and average the four reward fields. To stay responsive we only decompose
    evals whose samples are already cached OR (if network on) up to a cap.
    """
    groups: dict[str, dict] = {}
    for r in records:
        if r["status"] != "COMPLETED" or r["variant"] is None:
            continue
        comps = _eval_components(r["id"])
        if comps is None:
            # No cached samples and we don't want to block: bucket the sum
            # under scout as an "unsplit" total so the bar still sums right.
            comps = {c: 0.0 for c in REWARD_COMPONENTS}
            comps["_unsplit"] = float(r["score"] or 0.0)
        g = groups.setdefault(r["variant"], {c: 0.0 for c in REWARD_COMPONENTS} | {
            "_unsplit": 0.0, "n": 0, "total": 0.0, "seeds": set()})
        for c in REWARD_COMPONENTS:
            g[c] += comps.get(c, 0.0)
        g["_unsplit"] += comps.get("_unsplit", 0.0)
        g["total"] += float(r["score"] or 0.0)
        g["n"] += 1
        if r["seed"] is not None:
            g["seeds"].add(int(r["seed"]))
    out = {}
    for variant, g in groups.items():
        n = g["n"] or 1
        out[variant] = {c: g[c] / n for c in REWARD_COMPONENTS}
        out[variant]["_unsplit"] = g["_unsplit"] / n
        out[variant]["mean_total"] = g["total"] / n
        out[variant]["n_seeds"] = g["n"]
        out[variant]["seeds"] = sorted(g["seeds"])
    return out


def _eval_components(eval_id: str) -> Optional[dict]:
    """Average the four reward components across an eval's samples.

    Uses cached samples if present; otherwise pulls them (caching for next
    time). Returns None only if no samples are available at all.
    """
    cache = SAMPLES_DIR / f"{eval_id}.json"
    if cache.exists():
        try:
            payload = json.loads(cache.read_text())
        except json.JSONDecodeError:
            payload = None
    elif ALLOW_NETWORK:
        try:
            payload = fetch_samples(eval_id)
        except RuntimeError:
            payload = None
    else:
        payload = None
    if not payload:
        return None
    samples = payload.get("samples") or []
    if not samples:
        return None
    acc = {c: 0.0 for c in REWARD_COMPONENTS}
    for s in samples:
        for c in REWARD_COMPONENTS:
            acc[c] += float(s.get(c) or 0.0)
    n = len(samples)
    return {c: acc[c] / n for c in REWARD_COMPONENTS}


# --------------------------------------------------------------------------
# Rollout parsing — inlined from tools/render_rollout_video.py
# --------------------------------------------------------------------------
_MAP_BLOCK = re.compile(r"=== MAP ===\n(.+?)\n\n(?:===|$)", re.DOTALL)
_STATUS_LINE = re.compile(r"=== STATUS ===\n(.+?)$", re.MULTILINE)


def parse_observation(user_msg: str) -> dict:
    out = {"map": "", "status": "", "messages": "", "hint": ""}
    if not isinstance(user_msg, str):
        return out
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
    # Many turns carry an inline status header like
    # "[Moved E.] HP: 14/14  AC: 4  Dlvl: 1 ..." — surface it if no STATUS block.
    if not out["status"]:
        sm = re.search(r"(HP:\s*\S+.*?(?:Dlvl|Turn):.*)$", user_msg, re.MULTILINE)
        if sm:
            out["status"] = sm.group(1).strip()
    return out


def parse_tool_call(assistant_msg) -> str:
    if not assistant_msg:
        return "(no action)"
    tc = assistant_msg.get("tool_calls") if isinstance(assistant_msg, dict) else None
    if not tc:
        return "(no tool call)"
    first = tc[0]
    # Hosted samples sometimes encode each tool call as a JSON string.
    if isinstance(first, str):
        try:
            first = json.loads(first)
        except Exception:
            return first[:80]
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
    args_short = ", ".join(f"{k}={v}" for k, v in list(args_d.items())[:4])
    return f"{name}({args_short})"


def load_hosted_frames(eval_id: str) -> list[dict]:
    """Per-turn frames {turn, user_msg, assistant_msg, tool_call} from cache/API."""
    payload = fetch_samples(eval_id)
    samples = payload.get("samples") or []
    if not samples:
        return []
    s = samples[0]
    msgs = list(s.get("prompt") or []) + list(s.get("completion") or [])
    if not msgs:
        msgs = s.get("messages") or s.get("trajectory") or []
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
                "tool_call": parse_tool_call(m),
            })
            last_user = None
    # If the assistant spoke before any user obs (system+tools only), still
    # surface assistant turns paired with the most recent prompt user msg.
    if not frames:
        prompt_user = ""
        for m in (s.get("prompt") or []):
            if (m.get("role") or "").lower() == "user":
                prompt_user = m.get("content") or ""
        turn = 0
        for m in (s.get("completion") or []):
            if (m.get("role") or "").lower() == "assistant":
                turn += 1
                frames.append({
                    "turn": turn,
                    "user_msg": prompt_user,
                    "assistant_msg": m,
                    "tool_call": parse_tool_call(m),
                })
            elif (m.get("role") or "").lower() in ("tool", "user"):
                prompt_user = m.get("content") or prompt_user
    return frames


# --------------------------------------------------------------------------
# HTML rendering
# --------------------------------------------------------------------------
_CSS = """
<style>
 :root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#c9d1d9;--muted:#8b949e;
   --acc:#58a6ff;--green:#3fb950;--yellow:#d29922;--red:#f85149;--purple:#bc8cff;}
 *{box-sizing:border-box}
 body{background:var(--bg);color:var(--fg);font-family:-apple-system,Segoe UI,Roboto,sans-serif;
   margin:0;padding:0 24px 60px}
 a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
 h1{font-size:20px;margin:18px 0 4px} h2{font-size:15px;color:var(--muted);margin:24px 0 8px;
   border-bottom:1px solid var(--border);padding-bottom:4px}
 .bar{display:flex;align-items:center;gap:14px;padding:10px 0;flex-wrap:wrap}
 button,.btn{background:var(--panel);color:var(--fg);border:1px solid var(--border);
   border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
 button:hover,.btn:hover{border-color:var(--acc)}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{text-align:left;padding:5px 9px;border-bottom:1px solid var(--border);white-space:nowrap}
 th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--bg)}
 tr:hover td{background:var(--panel)}
 .pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600}
 .COMPLETED{background:#1f6f3f;color:#fff}.RUNNING,.PENDING{background:#9e6a00;color:#fff}
 .CANCELLED,.FAILED,.ERROR{background:#5a1d1d;color:#fff}
 .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
 .num{text-align:right;font-variant-numeric:tabular-nums}
 .stacked{display:flex;height:18px;border-radius:3px;overflow:hidden;min-width:60px;
   border:1px solid var(--border)}
 .seg{height:100%}
 .s-scout{background:var(--acc)}.s-descent{background:var(--green)}
 .s-success{background:var(--yellow)}.s-ascension{background:var(--purple)}
 .s-unsplit{background:#484f58}
 .legend span{display:inline-block;margin-right:14px;font-size:12px;color:var(--muted)}
 .legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:4px;
   vertical-align:middle}
 .map{font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.05;
   white-space:pre;background:#000;color:#d0d0d0;padding:12px;border-radius:8px;
   border:1px solid var(--border);overflow:auto}
 .panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px;
   margin:10px 0}
 .kv{color:var(--muted);font-size:12px}
 .tool{color:var(--green);font-family:ui-monospace,Menlo,monospace;font-size:14px}
 .status{color:var(--yellow);font-family:ui-monospace,Menlo,monospace;font-size:13px}
 .hint{color:var(--purple);font-size:12px;white-space:pre-wrap}
 .msgs{color:var(--acc);font-size:12px;white-space:pre-wrap}
</style>
"""


def _fmt_seed_set(seeds: list[int]) -> str:
    """Compress a sorted seed list into compact ranges, e.g. [22,23,24,31] -> '22-24,31'."""
    if not seeds:
        return "—"
    seeds = sorted(set(seeds))
    parts, start, prev = [], seeds[0], seeds[0]
    for s in seeds[1:]:
        if s == prev + 1:
            prev = s
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = s
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def _seg(comp_vals: dict, max_total: float) -> str:
    """Stacked horizontal bar for the four components (+ unsplit residual)."""
    if max_total <= 0:
        max_total = 1.0
    segs = []
    order = [("scout_reward", "s-scout"), ("descent_reward", "s-descent"),
             ("success_reward", "s-success"), ("ascension_reward", "s-ascension"),
             ("_unsplit", "s-unsplit")]
    for key, cls in order:
        v = comp_vals.get(key, 0.0)
        if v <= 0:
            continue
        pct = v / max_total * 100
        segs.append(f'<div class="seg {cls}" style="width:{pct:.2f}%" '
                    f'title="{key}={v:.3f}"></div>')
    return f'<div class="stacked">{"".join(segs)}</div>'


def render_overview(records: list[dict], agg: dict) -> str:
    # Aggregate table -----------------------------------------------------
    max_total = max((a["mean_total"] for a in agg.values()), default=1.0)
    agg_rows = []
    for variant in sorted(agg.keys()):
        a = agg[variant]
        cells = "".join(
            f'<td class="num mono">{a[c]:.3f}</td>' for c in REWARD_COMPONENTS)
        unsplit = f'<td class="num mono">{a["_unsplit"]:.3f}</td>'
        seedset = _fmt_seed_set(a.get("seeds") or [])
        agg_rows.append(
            f"<tr><td><b>{html.escape(variant)}</b></td>"
            f'<td class="num">{a["n_seeds"]}</td>'
            f'<td class="mono" style="font-size:11px;color:var(--dim)">{html.escape(seedset)}</td>'
            f'<td class="num mono"><b>{a["mean_total"]:.3f}</b></td>'
            f"{cells}{unsplit}"
            f"<td style='width:220px'>{_seg(a, max_total)}</td></tr>"
        )
    legend = (
        '<div class="legend">'
        '<span><i class="s-scout"></i>scout</span>'
        '<span><i class="s-descent"></i>descent</span>'
        '<span><i class="s-success"></i>success</span>'
        '<span><i class="s-ascension"></i>ascension</span>'
        '<span><i class="s-unsplit"></i>unsplit total</span>'
        "</div>"
    )
    agg_table = (
        "<table><thead><tr><th>variant</th><th class=num>n</th>"
        "<th>seed set</th>"
        "<th class=num>mean score</th><th class=num>scout</th>"
        "<th class=num>descent</th><th class=num>success</th>"
        "<th class=num>ascension</th><th class=num>unsplit</th>"
        "<th>decomposition</th></tr></thead><tbody>"
        + ("".join(agg_rows) or "<tr><td colspan=10>no COMPLETED variant evals</td></tr>")
        + "</tbody></table>"
        + '<p class="kv" style="color:var(--dim)">Variants are evaluated over '
        "different seed sets — compare rates only within a shared seed set, "
        "not across the raw aggregate.</p>"
    )

    # Raw list ------------------------------------------------------------
    raw_rows = []
    for r in records:
        score = r["score"]
        score_s = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        link = (f'<a href="{url_for("replay", eval_id=r["id"])}">replay</a>'
                if r["status"] == "COMPLETED" and r["n_samples"] else "—")
        raw_rows.append(
            "<tr>"
            f'<td>{html.escape(r["variant"] or "—")}</td>'
            f'<td class="mono">{html.escape(str(r["model"]))}</td>'
            f'<td class="num">{r["seed"] if r["seed"] is not None else "—"}</td>'
            f'<td><span class="pill {html.escape(r["status"])}">{html.escape(r["status"])}</span></td>'
            f'<td class="num mono">{score_s}</td>'
            f'<td class="kv">{html.escape(r["created_at"][:19])}</td>'
            f'<td>{link}</td>'
            f'<td class="mono kv">{html.escape(r["id"])}</td>'
            "</tr>"
        )
    raw_table = (
        "<table><thead><tr><th>variant</th><th>model</th><th class=num>seed</th>"
        "<th>status</th><th class=num>score</th><th>created</th><th></th>"
        "<th>eval id</th></tr></thead><tbody>"
        + ("".join(raw_rows) or "<tr><td colspan=8>no evals cached</td></tr>")
        + "</tbody></table>"
    )

    n_done = sum(1 for r in records if r["status"] == "COMPLETED")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>NetHack eval dashboard</title>{_CSS}</head><body>
<div class="bar">
  <h1>NetHack eval dashboard</h1>
  <form method=post action="{url_for('refresh')}" style="margin:0">
    <button type=submit>↻ Refresh from prime</button></form>
  <span class="kv">{len(records)} evals · {n_done} completed</span>
</div>
<h2>Per-variant reward decomposition (COMPLETED only)</h2>
{legend}
{agg_table}
<p class="kv">avg_score = scout + descent + success + ascension (unweighted sum).
 "unsplit" = evals whose per-component split isn't cached yet — Refresh pulls
 samples to decompose them.</p>
<h2>All evals ({len(records)})</h2>
{raw_table}
</body></html>"""


def render_replay(eval_id: str, rec: Optional[dict], frames: list[dict]) -> str:
    n = len(frames)
    if n == 0:
        body = '<div class="panel">No turn frames could be parsed for this eval.</div>'
    else:
        # Pre-parse each frame's observation server-side; embed as JSON for JS.
        data = []
        for f in frames:
            obs = parse_observation(f["user_msg"])
            data.append({
                "turn": f["turn"],
                "map": obs["map"] or "(no map block this turn)",
                "status": obs["status"],
                "hint": obs["hint"],
                "messages": obs["messages"],
                "tool": f["tool_call"],
            })
        # Embed raw JSON in a <script type=application/json> block. Do NOT
        # HTML-escape it (textContent is read verbatim, entities are NOT
        # decoded) — only neutralize a literal </script> breakout.
        data_json = json.dumps(data).replace("</", "<\\/")
        body = f"""
<div class="bar">
  <button onclick="step(-1)">◀ Prev</button>
  <input id=slider type=range min=0 max={n-1} value=0 oninput="goto(+this.value)"
     style="flex:1;min-width:200px">
  <button onclick="step(1)">Next ▶</button>
  <span id=counter class="mono"></span>
</div>
<div class="panel">
  <div id=status class="status"></div>
  <div id=tool class="tool"></div>
</div>
<div id=map class="map"></div>
<div class="panel"><div class="kv">messages</div><div id=messages class="msgs"></div></div>
<div class="panel"><div class="kv">hint</div><div id=hint class="hint"></div></div>
<script id=frames type="application/json">{data_json}</script>
<script>
 const FR = JSON.parse(document.getElementById('frames').textContent);
 let i = 0;
 // Deep-link: #turn=N (1-based) jumps straight to that turn on load.
 (function(){{ const h=location.hash.match(/turn=(\\d+)/);
   if(h){{ i = Math.max(0, Math.min(FR.length-1, (+h[1])-1)); }} }})();
 function render(){{
   const f = FR[i];
   document.getElementById('counter').textContent = 'turn '+f.turn+' ('+(i+1)+'/'+FR.length+')';
   document.getElementById('status').textContent = f.status || '(no status)';
   document.getElementById('tool').textContent = '▶ ' + f.tool;
   document.getElementById('map').textContent = f.map;
   document.getElementById('messages').textContent = f.messages || '—';
   document.getElementById('hint').textContent = f.hint || '—';
   document.getElementById('slider').value = i;
 }}
 function goto(n){{ i = Math.max(0, Math.min(FR.length-1, n)); render(); }}
 function step(d){{ goto(i + d); }}
 document.addEventListener('keydown', e => {{
   if(e.key==='ArrowLeft') step(-1);
   if(e.key==='ArrowRight') step(1);
 }});
 render();
</script>
"""
    meta = ""
    if rec:
        score = rec["score"]
        score_s = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        meta = (f'<span class="kv">variant <b>{html.escape(rec["variant"] or "?")}</b> · '
                f'model <span class="mono">{html.escape(str(rec["model"]))}</span> · '
                f'seed {rec["seed"]} · score <b>{score_s}</b> · '
                f'<span class="pill {html.escape(rec["status"])}">{html.escape(rec["status"])}</span></span>')
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Replay {html.escape(eval_id)}</title>{_CSS}</head><body>
<div class="bar"><h1>Rollout replay</h1>
  <a class="btn" href="{url_for('overview')}">← back to overview</a></div>
<div class="bar"><span class="mono kv">{html.escape(eval_id)}</span> {meta}</div>
<p class="kv">Use ◀ ▶ buttons, the slider, or arrow keys to step through turns.</p>
{body}
</body></html>"""


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def overview():
    records = load_records()
    agg = aggregate_components(records)
    return render_overview(records, agg)


@app.route("/replay/<eval_id>")
def replay(eval_id: str):
    records = load_records()
    rec = next((r for r in records if r["id"] == eval_id), None)
    try:
        frames = load_hosted_frames(eval_id)
    except RuntimeError as exc:
        abort(502, description=str(exc))
    return render_replay(eval_id, rec, frames)


@app.route("/refresh", methods=["POST", "GET"])
def refresh():
    if ALLOW_NETWORK:
        fetch_eval_list(force=True)
    return redirect(url_for("overview"))


@app.route("/api/evals")
def api_evals():
    return jsonify(load_records())


@app.route("/api/eval/<eval_id>")
def api_eval(eval_id: str):
    return jsonify({
        "frames": load_hosted_frames(eval_id),
        "components": _eval_components(eval_id),
    })


@app.route("/healthz")
def healthz():
    return "ok"


# --------------------------------------------------------------------------
def main() -> None:
    global ALLOW_NETWORK
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-network", action="store_true", help="serve cache only")
    ap.add_argument("--refresh", action="store_true", help="force fresh pull on start")
    args = ap.parse_args()
    ALLOW_NETWORK = not args.no_network
    if args.refresh and ALLOW_NETWORK:
        print("Refreshing eval list from prime ...")
        fetch_eval_list(force=True)
    print(f"NetHack dashboard on http://{args.host}:{args.port}  "
          f"(network={'on' if ALLOW_NETWORK else 'off'}, cache={CACHE_DIR})")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
