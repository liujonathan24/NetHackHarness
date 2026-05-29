# NetHack LLM-agent: observation & harness experiments — progress report

_All results use a 9B open model on a fixed set of game seeds with a fixed per-game turn budget. "Descend" means the agent reached the second dungeon level, our current success objective._

**Base evaluation.** The baseline agent is shown the on-screen map and issues low-level moves one step at a time. In this setup it explores reasonably but almost never makes progress toward the goal: it circles the starting room, retraces the same steps, and eventually starves or dies on the first level — it descended in **0 of 4** games. See gif: `/Users/Fritz/Downloads/files/videos/seed24_dir8_COMPACTED.gif`. When we instead give the agent higher-level actions (e.g. "explore," "go to the stairs," "descend") rather than individual moves, behavior changes sharply: it reached the second level in **2 of 4** games — the only configuration that descended at all — versus 0 of 4 for the baseline. The gain is all-or-nothing (the agent either solves a game quickly or wanders until the turn budget runs out), so the rate still needs a larger run to confirm. Gif here: `/Users/Fritz/Downloads/files/videos/seed24_netplayN_COMPACTED.gif`.

**Reducing the observation size, and the overall picture.** A separate question is whether compressing the observation (a smaller, condensed view of the screen) costs us anything. It does not: the compressed and full-size views produce essentially the same outcomes, so compression is a cost saving, not a capability change — useful because it cuts the tokens per turn substantially. Putting all the comparisons together: the visual map is essential (replacing it with a text-only description of the scene collapses the agent's ability to play); the action interface is the one real capability lever (higher-level actions are what unlock descent); observation compression is free on the capability axis; and an explicit on-screen reminder to find and use the stairs did **not** help — spelling out the goal did not change the agent's exploration. The single reliable improvement to descent came from an automatic "unstick" mechanism that intervenes when the agent stalls in place. Side-by-side comparison gif: `/Users/Fritz/Downloads/files/videos/seed24_3panel_COMPACTED.gif`.

**What we have not reached, and the blockers.** We still do not have reliable descent — the agent reaches the second level only occasionally and on favorable games, and we have not pushed past it to deeper levels. Notably, scaling *up* the observation (showing the agent the complete, uncompressed screen every turn instead of a condensed view) did not help and in fact made play worse, because the larger input crowds out the agent's attention and bloats its context. The blockers are: (1) exploration strategy — the agent does not systematically search the level to reveal the downward staircase, which is the proximate cause of nearly every failure; (2) survival — games that drag on end in starvation or death before the agent finds the stairs; and (3) more observation is not the answer — capability is gated by how the agent acts and explores, not by how much of the screen it sees.

## The high-level action interface (NetPlay-style)

The configuration that unlocked descent replaces single-keypress movement with a
small set of **skills** — each one a scripted routine that can carry out many game
steps from a single decision, so the model reasons in terms of intent ("explore,"
"go downstairs") rather than individual moves. This follows the NetPlay approach
(Jeurissen et al., 2024). The baseline, by contrast, exposes only the eight
compass-direction moves, one step per decision.

The skills currently available to the agent, grouped by purpose:

- **Move & explore:** `autoexplore` (walk through unseen corridors/rooms until something noteworthy appears), `move_to` (path to a specific tile), `find_and_descend` (locate the down-stairs and go down in one call), `descend` (take the stairs under the agent), `search` (search adjacent walls/floor for hidden passages or doors, repeatable), `kick` (kick in a direction, e.g. to force a stuck door).
- **Fight & survive:** `attack` (attack in a direction), `engrave_elbereth` (write the protective ward to scare off monsters), `pray` (emergency appeal to the deity when starving or near death), `eat`, `quaff` (drink a potion), `read` (read a scroll).
- **Items:** `pickup` (pick up what's on the current tile).
- **Memory & knowledge:** `add_note` (record a fact in the journal), `pin_objective` (set the current goal, kept in view), `recall` (retrieve earlier notes), `wiki_lookup` / `wiki_search` (query an offline NetHack knowledge base about a monster, item, or situation).

The descent-focused variants narrow this set toward navigation (dropping item/knowledge
skills that proved to be turn sinks) and, in one variant, add a persistent on-screen
note about where the stairs are. As reported above, that added note did not change
behavior — the agent's limitation is in how it explores, not in the actions it has available.

## Where to add the GIFs

Already rendered (these show the **compressed** map — caption as the compressed/standard view):

- Side-by-side of the three control styles, one game: `/Users/Fritz/Downloads/files/videos/seed24_3panel_COMPACTED.gif`
- Low-level movement, single game: `/Users/Fritz/Downloads/files/videos/seed24_dir8_COMPACTED.gif`
- High-level skills, single game: `/Users/Fritz/Downloads/files/videos/seed24_netplayN_COMPACTED.gif`
- High-level skills + stair reminder, single game: `/Users/Fritz/Downloads/files/videos/seed24_salienceND_COMPACTED.gif`
- Earlier head-to-heads (skills vs. baseline): `/Users/Fritz/Downloads/files/videos/N22_vs_B1_22.gif`, `/Users/Fritz/Downloads/files/videos/N23_vs_B1_24.gif`

To be added once the in-progress runs finish — the **full, uncompressed** view (the game exactly as the model sees it, no compression):

- Low-level movement: `/Users/Fritz/Downloads/files/videos/seed24_dir8_RAW.gif`, `/Users/Fritz/Downloads/files/videos/seed22_dir8_RAW.gif`
- High-level skills: `/Users/Fritz/Downloads/files/videos/seed24_netplayN_RAW.gif`, `/Users/Fritz/Downloads/files/videos/seed22_netplayN_RAW.gif`
- High-level skills + stair reminder: `/Users/Fritz/Downloads/files/videos/seed24_salienceND_RAW.gif`, `/Users/Fritz/Downloads/files/videos/seed22_salienceND_RAW.gif`
