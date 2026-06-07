"""
nethack_harness.tools.wiki
=================

A small NetHack wiki retrieval layer. Two access patterns:

* `wiki_lookup(entity)` — fetch a single named page exact-match.
* `wiki_search(query, k=3)` — return top-k pages whose title or body
  contains the query substring.

Why this is a *stub* and not a vector index:

We use substring matching because (a) the wiki snapshot at v0 is a flat
JSON we don't yet ship, (b) substring is ~25 µs per call vs ~10 ms for a
ChromaDB vector lookup — fine at 50-page volume, swap when we have 1000+.
The skill API is the same either way; the impl swap is opaque to the agent.

The `prime-rl/examples/wiki_search` pattern is what we'd port for the
ChromaDB version. Behind an extras dep:

    [project.optional-dependencies]
    wiki = ["chromadb>=0.4", "sentence-transformers>=2.2"]

Snapshot acquisition (future work):
    git clone https://github.com/nethackwiki/nethackwiki-mirror.git
    python tools/build_wiki_index.py --out ~/.cache/nethack-rl/wiki.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class WikiPage:
    title: str
    body: str

    def short(self, max_chars: int = 400) -> str:
        return self.body[:max_chars].rstrip() + ("…" if len(self.body) > max_chars else "")


class WikiIndex:
    """In-memory substring index. Loaded from a JSON or constructed inline."""

    def __init__(self, pages: Optional[list[WikiPage]] = None):
        self._pages: list[WikiPage] = list(pages or [])
        self._by_title: dict[str, WikiPage] = {p.title.lower(): p for p in self._pages}

    def add(self, title: str, body: str) -> None:
        p = WikiPage(title=title, body=body)
        self._pages.append(p)
        self._by_title[title.lower()] = p

    def lookup(self, entity: str) -> Optional[WikiPage]:
        return self._by_title.get(entity.strip().lower())

    def search(self, query: str, k: int = 3) -> list[WikiPage]:
        q = query.strip().lower()
        if not q:
            return []
        hits: list[tuple[int, WikiPage]] = []
        for p in self._pages:
            score = 0
            if q in p.title.lower():
                score += 10  # title match weighted higher
            score += p.body.lower().count(q)
            if score > 0:
                hits.append((score, p))
        hits.sort(key=lambda t: -t[0])
        return [p for _, p in hits[:k]]

    @classmethod
    def from_json(cls, path: Path) -> "WikiIndex":
        data = json.loads(Path(path).read_text())
        return cls(pages=[WikiPage(title=d["title"], body=d["body"]) for d in data])

    @classmethod
    def default(cls) -> "WikiIndex":
        """A tiny built-in index seeded with high-value monster/object pages.

        Useful for dev testing without downloading the full wiki. Replace
        with `from_json(<snapshot>)` for real use.
        """
        return cls(pages=[
            WikiPage(title="cockatrice", body=(
                "A small reptile whose touch petrifies. Wear gloves before "
                "wielding the corpse. Touching a cockatrice body with bare "
                "hands is fatal. Recommended: carry a stack of paper, "
                "engrave Elbereth, then read."
            )),
            WikiPage(title="mine town", body=(
                "Mine Town is a settlement in the Gnomish Mines branch, "
                "typically dlvl 5-8. Contains shops, an altar (sometimes), "
                "the priest, and watchmen who will attack chaotic players "
                "for early infractions."
            )),
            WikiPage(title="sokoban", body=(
                "A branch entered from a fork off the main dungeon. Four "
                "puzzle levels of boulder-pushing; complete to be granted "
                "the Bag of Holding or Amulet of Reflection (random per "
                "game). Cheating (using boulders for any other purpose) "
                "incurs a luck penalty."
            )),
            WikiPage(title="oracle", body=(
                "The Oracle of Delphi resides on a unique level in the "
                "main dungeon, ~dlvl 5-9. Pay-to-consult: 50zm for a minor "
                "hint, 200-400zm for a major prediction. Major consultation "
                "is required to start your role's quest."
            )),
            WikiPage(title="elbereth", body=(
                "An engraved or written word that frightens most monsters. "
                "Engrave with E. command on the floor. Note: Bones of "
                "previous adventurers and some monsters (humans, @) are "
                "not affected."
            )),
            WikiPage(title="altar", body=(
                "Tiles marked _ can be used to identify alignment and "
                "bless/curse items by dropping them on the altar. Pray on "
                "an altar of your alignment for divine help. Praying on a "
                "cross-aligned altar is dangerous."
            )),
        ])


def _load_default_index() -> WikiIndex:
    """Load the bundled wiki snapshot if present, fall back to the 6-page seed.

    Looks for `wiki/snapshot.json` relative to the project root. This makes
    the env's `wiki_lookup` / `wiki_search` skills hit real wiki content by
    default once `tools/build_wiki_index.py` has been run.
    """
    # Try the workspace-root snapshot.
    candidates = [
        Path(__file__).resolve().parents[1] / "wiki" / "snapshot.json",
        # Hub install: nethack_core is vendored under environments/nethack/
        Path(__file__).resolve().parents[1] / ".." / "wiki" / "snapshot.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return WikiIndex.from_json(p)
            except Exception:
                continue
    return WikiIndex.default()


# Singleton default index used by the skill wrappers. Hot-swap via set_index.
_DEFAULT_INDEX = _load_default_index()


def get_index() -> WikiIndex:
    return _DEFAULT_INDEX


def set_index(index: WikiIndex) -> None:
    """Hot-swap the global index (used by tests and the wiki-snapshot loader)."""
    global _DEFAULT_INDEX
    _DEFAULT_INDEX = index


def reload_default_index() -> WikiIndex:
    """Force re-load of the bundled snapshot. Useful after editing it."""
    global _DEFAULT_INDEX
    _DEFAULT_INDEX = _load_default_index()
    return _DEFAULT_INDEX
