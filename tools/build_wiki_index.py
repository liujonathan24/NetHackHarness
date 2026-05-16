"""Scrape the NetHack wiki and emit a JSON snapshot consumable by WikiIndex.

Usage:
    python tools/build_wiki_index.py --out wiki/snapshot.json
    python tools/build_wiki_index.py --out wiki/snapshot.json --pages cockatrice mine_town sokoban
    python tools/build_wiki_index.py --out wiki/snapshot.json --topics monsters_seed

Then load:
    from nethack_core.wiki import WikiIndex, set_index
    set_index(WikiIndex.from_json("wiki/snapshot.json"))

The default scrape pulls a curated 30-page seed list (high-utility monster +
strategy + branch pages). Pass `--full` to walk the entire AllPages list
(~3000 pages, ~5MB JSON, ~20min runtime).

Polite scraping: 1 req/sec by default, configurable via --delay. Skips images.
Caches per-page HTML in a tmpfs dir so reruns are cheap.

NB: the wiki has no public API. We HTML-scrape and clean. The Mediawiki
markup → plaintext conversion is approximate; for high-stakes use point
the index at the wiki's `extract` API endpoint instead.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

WIKI_BASE = "https://nethackwiki.com"
USER_AGENT = "nethack-rl/0.1 (research; jl0796@princeton.edu)"

# A 30-page curated seed list. Add/remove freely; this is the smallest set
# we think gives an LM useful coverage of common NetHack scenarios.
SEED_PAGES = [
    # monsters — dangerous letter-class encounters the LM is likely to hit
    "cockatrice", "lich", "mind_flayer", "demogorgon", "leprechaun",
    "nymph", "rust_monster", "trapper", "watchman", "shopkeeper",
    "jackal", "kobold", "newt", "sewer_rat", "grid_bug", "yellow_light",
    "gnome", "dwarf", "elf", "drow", "giant", "naga", "dragon",
    "ghost", "wraith", "shade", "vampire", "werewolf", "minotaur",
    "soldier_ant", "blue_jelly", "spotted_jelly",
    # branches & special levels
    "mine_town", "gnomish_mines", "sokoban", "oracle",
    "vlad's_tower", "valley_of_the_dead", "castle",
    "medusa", "dungeons_of_doom", "quest", "gehennom",
    "plane_of_earth", "plane_of_water", "plane_of_air", "plane_of_fire",
    "astral_plane", "high_altar",
    # strategy / mechanics
    "elbereth", "altar", "praying", "scroll_of_identify",
    "amulet_of_yendor", "wand_of_wishing", "armor", "weapon",
    "potion", "ring", "stoning", "petrification", "polymorph",
    "fountain", "throne", "sink", "grave", "cursed", "blessed",
    "hunger", "hp_regeneration", "luck", "stealth",
    "intrinsic", "extrinsic", "alignment", "deity", "experience_level",
    "engraving", "reading", "wishing",
    # roles (all 13 main)
    "archeologist", "barbarian", "caveman", "healer", "knight",
    "monk", "priest", "rogue", "ranger", "samurai", "tourist",
    "valkyrie", "wizard",
    # races (under Race in NetHackWiki — not the same as the role pages)
    "human", "race",
    # essential items
    "magic_marker", "bag_of_holding", "magic_lamp", "unicorn_horn",
    "amulet_of_life_saving", "ring_of_polymorph_control",
    "scroll_of_magic_mapping",
]


def _strip_html(text: str) -> str:
    """Approximate HTML → plain text: drop tags, normalize whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_lead_section(html: str) -> str:
    """Pull the first content paragraphs from a Mediawiki rendered page.

    Stops at the first <h2> heading (which marks the end of the lead section
    in Mediawiki's default render).
    """
    # Find the content body (mw-parser-output).
    m = re.search(r'<div class="mw-parser-output"[^>]*>(.*?)<div class="printfooter"', html, re.DOTALL)
    body = m.group(1) if m else html
    # Truncate at first major heading.
    body = re.split(r"<h2", body, 1)[0]
    text = _strip_html(body)
    # Cap at ~1500 chars; the seed pages are short by design.
    return text[:1500].strip()


def _fetch(url: str, cache: Path | None = None) -> str:
    if cache is not None and cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(html, encoding="utf-8")
    return html


def scrape_one(slug: str, cache_dir: Path | None) -> dict:
    """Return {'title': ..., 'body': ...} for one wiki page slug.

    Uses the Mediawiki API's `prop=extracts&exintro=1&explaintext=1` which
    gives the lead section as plain text (much cleaner than HTML scraping).
    Falls back to HTML extraction if the API returns nothing.
    """
    title = slug.replace("_", " ")
    # exintro=1 misses pages whose lead section is empty (just tables). Drop
    # the exintro flag and cap with exchars so we always get *some* prose.
    api_url = f"{WIKI_BASE}/api.php?" + urllib.parse.urlencode({
        "action": "query", "prop": "extracts",
        "explaintext": "1", "format": "json",
        "exchars": "1800",
        "titles": title.title(),
    })
    cache = cache_dir / f"{slug}.api.json" if cache_dir else None
    raw = _fetch(api_url, cache=cache)
    body = ""
    try:
        import json as _json
        data = _json.loads(raw)
        pages = data.get("query", {}).get("pages", {})
        for _pid, page in pages.items():
            if page.get("extract"):
                body = page["extract"][:1500].strip()
                break
    except Exception:
        body = ""

    if not body:
        # Fallback: HTML scrape.
        html_url = f"{WIKI_BASE}/wiki/{urllib.parse.quote(slug)}"
        html_cache = cache_dir / f"{slug}.html" if cache_dir else None
        html = _fetch(html_url, cache=html_cache)
        body = _extract_lead_section(html)

    if not body:
        body = f"(empty extraction for {title.lower()}; see {WIKI_BASE}/wiki/{urllib.parse.quote(slug)})"
    return {"title": title.lower(), "body": body}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="Output JSON path")
    p.add_argument("--pages", nargs="+", help="Specific page slugs to scrape (overrides defaults)")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (politeness)")
    p.add_argument("--cache", default="/tmp/nethack_wiki_cache", help="Cache directory for raw HTML")
    p.add_argument("--full", action="store_true", help="Scrape the full Special:AllPages list (slow)")
    args = p.parse_args()

    if args.full:
        print("--full not implemented yet; using SEED_PAGES (30 pages)", file=sys.stderr)

    targets: Iterable[str] = args.pages or SEED_PAGES
    cache_dir = Path(args.cache) if args.cache else None
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pages: list[dict] = []
    failures: list[str] = []
    for i, slug in enumerate(targets):
        try:
            page = scrape_one(slug, cache_dir)
            pages.append(page)
            print(f"[{i+1}/{len(list(targets))}] {slug}: {len(page['body'])}b")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            failures.append(f"{slug}: {e}")
            print(f"[{i+1}/?] {slug}: FAILED ({e})", file=sys.stderr)
        if i < len(list(targets)) - 1 and args.delay > 0:
            # Respect cache: if cache hit, no need to throttle.
            cached = (cache_dir / f"{targets[min(i+1, len(targets)-1)]}.html") if cache_dir else None
            if cached is None or not cached.exists():
                time.sleep(args.delay)

    out_path.write_text(json.dumps(pages, indent=2))
    print(f"\nWrote {len(pages)} pages to {out_path} ({out_path.stat().st_size}b)")
    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures:
            print(f"  {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
