# Prompting Survey: Game-Agent Harnesses and Token Management

A survey of how production / research LM agent harnesses format game state and
control context growth, with concrete recommendations for `nethack-rl`.

## Comparison Table

| System | Observation format | History management | Action space | Notes |
|---|---|---|---|---|
| Claude Plays Pokemon (Anthropic, 2025) | Raw screenshot + structured "knowledge base" tool outputs | Periodic summarization: at N-turn threshold Claude writes a long summary, full chat history cleared | Tool calls: `press_button`, `navigate_to(x,y)`, `update_knowledge_base` | Persistent KB is the long-term memory; chat is disposable |
| Gemini Plays Pokemon (jcz, 2025) | Annotated screenshots: memory dumps converted to text grid (tile properties, navigability, NPC positions); raw pixels found unreliable | Summarize-and-reset every ~100 turns. Persistent "goals" (primary/secondary/tertiary) survive resets. Notepad + map markers + mental map persist | Discrete button per step + custom python tools (pathfinder, sub-agents) | Goals system is the durable belief-state |
| BALROG (Paglieri et al., ICLR 2025) | Natural-language observation OR multimodal image; NetHack text wrapper renders glyphs + messages + status | Fixed sliding window of last K messages; no learned summarization in benchmark code | Free-text -> parsed action keyword from a fixed verb list | VLM scored *worse* than pure-text on NetHack |
| Glyphbox (Ken Wang, Jan 2026) | ASCII map + player coords + adjacent-tile descriptions (N/NE/E/...) + visible-hostile list + inventory + last-turn game messages | Past map state stripped from history; after turn 10 tool args -> `<compacted>`; after turn 100 messages dropped entirely | Single `execute_code` tool exposing a Python NetHack API; lets the model write loops over many in-game ticks in one tool call | The Python-API + loop pattern is the biggest token win they report |
| NetPlay (Jeurissen, CoG 2024) | NetHack text obs + task description + skill list, packaged as past-event messages | Past-event messages kept; skill abstraction means many low-level turns collapse to one LLM call | Predefined skills (`move_to x y`, `pickup_item`, ...) chosen each LLM step | Skills are the compaction mechanism |
| Motif (Klissarov, NeurIPS 2023) | Message-only captions (no map) shown to Llama-2-70B for pairwise preference | N/A — offline preference labeling, not online play | Preference between two short text captions | Shows the *message log* alone carries most of the signal |
| Cicero (FAIR, 2022) | Structured game state: board, units, centers, recent orders + dialogue history per dyad | Per-dyad rolling dialogue; game history compressed to order-list | Dialogue text + planned order set | LM is conditioned on planner's intent, not raw history |
| LLM Chess (various) | FEN string + explicit legal-moves list | Stateless: FEN already encodes full state; PGN sometimes appended | Choose move from supplied legal list | Canonical example of "state replaces history" |
| TextStarCraft II / LLM-PySC2 (NeurIPS 2024/2025) | Hand-built text rendering of PySC2 obs | "Chain of Summarization": single-frame summary + multi-frame summary, cascading | Sub-set of PySC2 commands, text -> function call | CoS explicitly designed for long-horizon RTS |
| AlphaStar (DeepMind, 2019) | Feature layers (128x128 spatial + up-to-512 unit list) | LSTM hidden state — not text | 1026-dim action head | Reference point for "what dense features look like" |
| Voyager (Wang et al., 2023) | Brief env snapshot + retrieved top-5 skills from skill library | Curriculum + skill-library (vector-indexed) as long-term memory; chat itself is a 4-round refinement loop, then discarded | Generated JavaScript that calls Mineflayer API | Skill library = compaction by *amortizing* successful trajectories |
| SWE-agent (NeurIPS 2024) | File windows + diff snippets via ACI commands | "Elide all but last 5 observations": older obs replaced with `Old environment output: (n lines omitted)` | Constrained shell-like commands (`edit`, `goto`, ...) | Last-K elision is their default; informative error msgs cut retries |
| OpenHands (ICLR 2025) | Event log: action/observation pairs as structured messages | Pluggable "condensers": default condenser claims ~2x cost cut on long sessions with no measurable quality loss; explicit `condensation_request` tool the agent can invoke | CodeAct: Python in a sandbox + browse + bash | Condenser is a separate component, not the main LM |

---

## Per-System Notes

### Claude Plays Pokemon (Anthropic, Twitch 2025–)
Screenshot in, button-press tool calls out. The main trick is that conversation
history would blow past 200k well before the first badge, so the harness
periodically asks Claude itself to write a detailed prose summary of recent
events, *then deletes the raw chat*. Long-term memory lives in an explicit
"knowledge base" tool the model writes to (maps, NPC notes, what's in each
building). The model is told NOT to rely on prior Pokemon knowledge — only the
KB and current screen. Source: <https://michaelyliu6.github.io/posts/claude-plays-pokemon/>,
<https://www.latent.space/p/how-claude-plays-pokemon-was-made>.

### Gemini Plays Pokemon (jcz blog, 2025)
Found raw pixels unreliable; harness extracts from game memory and renders a
*text* grid with tile properties, NPC positions, and per-direction
navigability. Summarize-and-reset every ~100 turns; a "goals" structure
(primary/secondary/tertiary) is the persistent belief state across resets, plus
a notepad, map markers, and a "mental map". Sub-agents for special reasoning
tasks (e.g. battle planning) and a code-execution tool for pathfinding.
Source: <https://blog.jcz.dev/the-making-of-gemini-plays-pokemon>.

### BALROG (Paglieri et al., ICLR 2025)
Standardized benchmark across BabyAI, Crafter, TextWorld, BabaIsAI, MiniHack,
NetHack. Default obs: NLE text wrapper (glyph descriptions + messages + status
+ inventory) OR image. Default history: sliding window of last-K messages.
Notable finding: VLMs do *worse* on NetHack when given the image vs text.
Source: <https://arxiv.org/abs/2411.13543>, <https://github.com/balrog-ai/BALROG>.

### Glyphbox (Ken Wang, Jan 2026)
Closest analog to `nethack-rl`. Obs is structured: ASCII map + player coords +
per-direction adjacent-tile descriptions + visible-hostile list + inventory +
last-turn game messages. History management is aggressive:
(1) past map states stripped entirely from history,
(2) tool-call arguments older than 10 turns -> `<compacted>` placeholder,
(3) messages older than 100 turns dropped wholesale.
Single `execute_code` tool exposes a Python NetHack API
(`nh.get_adjacent_hostiles()`, `nh.attack(dir)`), so one LM step can do dozens
of in-game ticks via a python loop. This is the article's headline efficiency
trick. Source: <https://kenforthewin.github.io/blog/posts/nethack-agent/>.

### NetPlay (Jeurissen et al., CoG 2024)
LLM picks one *skill* per call from a predefined library
(`move_to x y`, `attack_monster`, `pickup_item`, ...). Each skill internally
executes many low-level actions, so the LM context grows in skill-units, not
NetHack-tick-units. Outperformed by autoascend but interpretable, follows
high-level instructions well. Source: <https://arxiv.org/abs/2403.00690>,
<https://github.com/CommanderCero/NetPlay>.

### Motif (Klissarov et al., NeurIPS 2023)
Not an online agent — uses Llama-2-70B *offline* to label pairs of NetHack
*message-only* captions with preferences, distills into an intrinsic reward,
trains an RL agent on top. The relevant lesson for us: the NetHack message log
alone, with no map, carries enough semantic signal to rank events. Source:
<https://arxiv.org/abs/2310.00166>, <https://github.com/facebookresearch/motif>.

### Cicero (Bakhtin et al., Science 2022)
Not LLM-prompting per se, but the canonical example of conditioning a language
model on a planner's *intent* rather than feeding it raw history. Each dyad
gets a rolling local dialogue; full game state is compressed to current
centers/units + recent order list. Source:
<https://www.science.org/doi/10.1126/science.ade9097>.

### LLM Chess
Standard pattern is FEN + explicit legal-move list. FEN is ~70 tokens and
fully describes state, so history is mostly redundant. Reinforces that
*compact canonical state strings beat conversation history* when state is
fully observable. Source: <https://arxiv.org/abs/2512.01992>,
<https://arxiv.org/html/2501.17186v2>.

### TextStarCraft II + LLM-PySC2 (NeurIPS 2024 / 2025)
"Chain of Summarization": every frame gets a single-frame summary; periodically
those are combined into a multi-frame strategic summary. Two-level hierarchy,
not just one rolling summary. Defeats LV5 built-in AI with most LLMs tested.
Source: <https://arxiv.org/abs/2312.11865>, <https://arxiv.org/html/2411.05348v1>.

### AlphaStar (DeepMind 2019)
Reference point only — feature-layer observations + LSTM hidden state. Tells
us how much information a competent player wants per step (dense feature
layers, full unit list), which is sobering: text observations are necessarily
lossy. Source: <https://deepmind.google/blog/alphastar-mastering-the-real-time-strategy-game-starcraft-ii/>.

### Voyager (Wang et al., 2023)
Long-term memory lives in a vector-indexed *skill library*: each successful
JS function is stored with a natural-language description and re-retrieved
top-5 on new tasks. Chat history is *not* kept — only the last 4-round
refinement loop. Source: <https://arxiv.org/abs/2305.16291>.

### SWE-agent (Yang et al., NeurIPS 2024)
Default history processor elides everything except the last 5 observations,
replaced by `Old environment output: (n lines omitted)`. Prompts and error
messages are carefully shaped to avoid retry loops. Source:
<https://arxiv.org/pdf/2405.15793>, <https://swe-agent.com/latest/reference/history_processor_config/>.

### OpenHands (Wang et al., ICLR 2025)
Architecturally separates the event-log state from the LM input via swappable
"condensers". Default condenser cuts cost ~2x with no measurable quality loss.
Also exposes a `condensation_request` so the agent itself can ask to compact.
Source: <https://arxiv.org/pdf/2407.16741v2>,
<https://docs.openhands.dev/openhands/usage/developers/evaluation-harness>.

---

## Recommendations for `nethack-rl`

Concrete token-reduction strategies, ranked by expected impact for our
chat-formatted, ~150-turn, ~4M-token regime.

### Implementation status (as of v0.0.23)

| # | Recommendation | Status | Hub version |
|---|----------------|--------|------------|
| 1 | Drop historical map renderings from chat | ✓ implemented | v0.0.18 |
| 2 | Two-level history compaction (keep 5, summarize 6..100, drop >100) | ✓ implemented | v0.0.18 |
| 3 | Periodic SubLM belief-state summary (every 25 turns) | ✓ implemented | v0.0.19 |
| 4 | Inventory diff-only | ✓ implemented | v0.0.17 |
| 5 | Message run-length encoding | ✓ implemented | v0.0.20 |
| 6 | Strip blank tty rows | ✓ implemented | v0.0.17 |
| 7 | Compact action-history footer | ⊘ not implemented | — |
| 8 | Glyph-run encoding of map rows (`.{20}`) | ✓ implemented | v0.0.17 |
| 9 | Journal append-only diff | ⊘ partial — added a render cap (v0.0.22) but not per-turn diff |
| 10 | Action space: optional code-mode tool | ✓ already shipped pre-survey | v0.0.8 |

**Measured savings (exp15_token_savings.py, 60-turn synthetic rollout):**
- Per-turn obs: **25.7% smaller** (recs 4 + 5 + 6 + 8)
- **Cumulative prompt: 89.8% smaller** (above + recs 1 + 2)

Tunable via `load_environment(...)` kwargs as of v0.0.23: `compact_obs`,
`history_keep_full`, `history_drop_after`, `belief_state_interval`,
`journal_render_max_chars`. Pass `compact_obs=False` to A/B against the
v0.0.15-era baseline.

### 1. Drop historical map renderings from chat (BIG WIN, easy)
The tty grid is the dominant per-turn payload (~24 lines * ~80 cols ~= 2k
tokens). After a turn, the *previous* tty grid is almost never needed — the
current one supersedes it. Glyphbox strips it entirely; we should do the same.
Keep last 1–2 grids at most, replace older ones with a short locator
(e.g. `[map @ turn 47 elided]`). Expected: ~80–90% reduction in tty-related
tokens, which is most of the 4M.

### 2. Two-level history compaction a la SWE-agent / Glyphbox
Last K (K=5–10) turns full fidelity; older turns: keep only the action +
one-line outcome, drop the inventory/journal/tty entirely. Beyond N=100 turns,
drop the message wholesale (or replace with a single rolled-up summary line).
This is exactly the SWE-agent / Glyphbox pattern and is cheap to implement.

### 3. Periodic SubLM belief-state summary (we already have the substrate)
Every ~25 turns, call our SubLM to emit a 200–400-token "current situation"
brief (level, location, HP trajectory, last 3 strategic goals, threats,
inventory deltas). Drop or compact everything before it. This is the Claude
Plays Pokemon / Gemini Plays Pokemon / TextStarCraft CoS pattern. The belief
state becomes the durable memory; the chat is disposable.

### 4. Inventory diff-only (medium win)
Most turns the inventory is unchanged. Emit inventory in full only when it
changes; otherwise a single `inventory: unchanged` line. Track a checksum
across turns. Easy 10–20% win on long stretches of exploration/combat.

### 5. Message-line run-length encoding
Combat spam like `You hit the kobold.` x10 -> `You hit the kobold. (x10)`.
Same for `You miss.`, `It hits!`, etc. Apply within a single message buffer
and also across consecutive turns where the *only* message is identical.
Easy, surprisingly large in long fights.

### 6. Strip blank rows / trailing-blank trim of tty
NetHack's tty has many empty rows (status line area, post-message blanks).
Cheap text-side: strip trailing whitespace per row, drop fully-blank rows that
aren't load-bearing for spatial reasoning. ~15–25% off the *current* map
payload.

### 7. Compact action-history footer instead of full per-step messages
Maintain a separate "last 20 actions: N,N,E,attack,N,pick,..." footer; drop
those steps from the chat entirely. Mirrors Cicero's "order list" compression.
LM gets temporal context cheaply.

### 8. Glyph-run encoding of map rows
Long runs of `.` (floor) or `#` (corridor) -> `.{15}`. Lossless, halves typical
dungeon-row length. Pair with #1/#6 for max effect.

### 9. Journal: switch to append-only diff
The journal field grows monotonically. Show only deltas since last shown
journal (or last belief-state summary). Old entries live in the belief state.

### 10. Action space: optional Python-API tool a la Glyphbox
Out of the pure token-formatting scope, but worth noting: one
`execute_code` tool with helpers like `attack_until_dead(dir)`,
`walk_to(x,y)`, drops the *number* of LM calls per dungeon level by an order
of magnitude. Multiplicatively compounds with all the above.

### Prompting-side knobs we should add

- `obs.verbosity`: `minimal | standard | verbose`. Minimal = map + status +
  last messages only; verbose = everything we currently send.
- `obs.fields`: opt-in set, e.g. `{tty, status, inventory, journal, messages,
  adjacency, hostiles}`. Default-on subset is small; the LM can request more
  via a `request_field` tool (mirrors OpenHands' `condensation_request`).
- `history.window`: K most-recent turns kept full-fidelity (default 5).
- `history.drop_old_maps`: bool (default true).
- `history.compact_after`: turn count after which old turns collapse to
  one-liners (default 10).
- `history.drop_after`: turn count after which old turns are dropped entirely
  (default 100).
- `belief_state.enabled` + `belief_state.interval`: SubLM summary every N
  turns (default 25); summary inserted as a "system note" message and
  preceding turns become eligible for full drop.
- `inventory.diff_only`: bool (default true).
- `messages.dedup_run_length`: bool (default true).
- `tty.strip_blank_rows`, `tty.glyph_runs`: bool/bool.

### Expected combined impact

Items 1+2+6+8 alone should cut per-turn payload by ~3–5x on map/tty alone,
which dominates current cost. Adding 3 (belief-state) flattens the
*linear-in-turns* growth to roughly constant + log. Target: 4M tokens / 150
turns (~27k/turn avg) -> <5k tokens/turn average and *bounded* in turn count.
