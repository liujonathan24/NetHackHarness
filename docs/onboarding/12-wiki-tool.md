# Wiki tool: in-game lore as a skill

**Status:** Shipped in `nethack_core/wiki.py` + two new skills in
`nethack_core/skills.py` as of Day 3. Tested in `tests/test_wiki.py`.

**v0.0.28 update:** Now auto-loads a bundled 102-page wiki snapshot
(`wiki/snapshot.json`) at module import via `_load_default_index()`.
The 6-page dev stub is only used when the snapshot is missing. Hub
installs include the snapshot via `force-include` in the wheel.

To regenerate the snapshot (e.g. after updating SEED_PAGES in
`tools/build_wiki_index.py`):
```bash
python tools/build_wiki_index.py --out wiki/snapshot.json
python tools/bundle_for_hub.py   # vendors into environments/nethack/wiki/
```

## Why this matters

Alex Zhang specifically called out wiki integration as an "incorporate the
wiki natively as part of the environment" want, channeling the Pokemon
strategy of an agent reading the wiki tab between turns. NetHack has the
deepest roguelike wiki on the internet — over 6000 pages — and an agent
that can query it on demand has a categorical advantage over one that has
to memorize NetHack 3.6 trivia from training.

## The API

Two skills, registered through the same `SkillRegistry`:

```python
wiki_lookup(entity: str)             # exact-match page fetch
wiki_search(query: str, k: int = 3)  # substring-rank top-k pages
```

Both return a `SkillResult` with no env-step actions and the lookup body in
`feedback`. The verifiers env renders feedback above the next observation.

## The implementation (`wiki.py`)

```python
@dataclass
class WikiPage:
    title: str
    body: str
    def short(self, max_chars: int = 400) -> str: ...

class WikiIndex:
    def lookup(self, entity: str) -> Optional[WikiPage]
    def search(self, query: str, k: int = 3) -> list[WikiPage]
    @classmethod
    def from_json(cls, path: Path) -> WikiIndex
    @classmethod
    def default(cls) -> WikiIndex  # tiny seeded index for dev
```

A global singleton `_DEFAULT_INDEX` is set to the dev-time default. Hot-
swap with `set_index(WikiIndex.from_json(...))` once a real snapshot lands.

### Search ranking

Substring match with two priors:

- Title match weighted ×10 over body match.
- Body match count linear (more occurrences = higher rank).

Cheap, correct enough for a 6-page seeded index, and identical interface to
a future ChromaDB version. Switching from substring to embedding requires
no skill-API change.

## Why substring and not a vector index for v0

- **Volume**: the seeded index is 6 pages. Substring is ~25 µs/call;
  ChromaDB lookup is ~10 ms. At 6 pages embedding indexes pay overhead
  with no benefit.
- **Determinism**: substring is bit-identical across runs. Embedding
  lookups have nondeterminism in the embedding backend, which would break
  our reproducibility audit.
- **Install footprint**: no `chromadb` / `sentence-transformers` dep.
  Keeps `nethack_core` install thin.
- **Upgrade path**: when we have a real wiki snapshot (~6000 pages), `from
  prime-rl/examples/wiki_search` is the canonical reference. Wrap behind
  the existing extras dep:

  ```toml
  [project.optional-dependencies]
  wiki = ["chromadb>=0.4", "sentence-transformers>=2.2"]
  ```

  and switch the global index loader to detect the extras and prefer
  ChromaDB when available. Skill API doesn't change.

## How to use

```python
from nethack_core.skills import wiki_lookup, wiki_search

# Direct:
r = wiki_lookup(env, obs, entity="cockatrice")
print(r.feedback)   # "[wiki: cockatrice] A small reptile whose touch petrifies..."

# Or via the skill registry (what the verifiers harness does):
from nethack_core.skills import registry
r = registry.call("wiki_search", env, obs, query="altar", k=2)
```

The model just needs to issue `wiki_lookup({"entity": "cockatrice"})`. The
journal pairs nicely: after looking up a monster the agent saw, the result
gets stored as a note.

## Future work

- **Real wiki snapshot loader.** Build `tools/build_wiki_index.py` that
  scrapes nethackwiki.com (CC-BY-SA, attribute) and emits JSON. Persist at
  `~/.cache/nethack-rl/wiki.json`.
- **Auto-lookup on new glyphs.** When the env detects a glyph the agent
  has never seen, optionally prepend a `wiki_lookup` hint in the next
  observation. Cheap. Closes the "model has to learn to ask" gap.
- **ChromaDB swap behind the extras dep.** Move the singleton creation into
  a factory that detects the extras and uses ChromaDB if installed.
- **Wiki-as-Motif-reward.** The wiki itself is a reward signal: if an
  agent's action matches wiki guidance for the current state, that's a
  pseudo-reward channel. Future research direction.

## How to verify

```bash
uv run pytest tests/test_wiki.py -v
```

Nine tests cover lookup (case insensitive, missing entity), search
(ranking, empty query, k cap), JSON roundtrip, set_index hot-swap, and the
WikiPage truncation.
