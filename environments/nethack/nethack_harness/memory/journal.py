"""
nethack_harness.memory.journal
====================

A structured note store the agent uses as long-horizon memory.

Pokemon-bench lesson (Claude Plays Pokemon, Gemini Plays Pokemon, 2025-2026):
the agent's scratchpad is load-bearing. Without persistent notes, the model
re-derives map state, item locations, and strategy every turn from raw
observation history. With notes, it accumulates knowledge and can act on it.

Three operations:

* `add_note(key, text)` — write a note under a slot (overwrite if exists).
* `recall(query)` — return notes whose key OR text contains the query
  substring (case-insensitive). Cheap retrieval; switch to embeddings later
  if the volume justifies it.
* `pin_objective(text)` — set the current top-level goal. Always rendered.

Why a key/text dict and not free-form append-only?
    The model needs to *overwrite* stale notes ("dragon was on dlvl 3" → "dragon
    killed"). Free-form append leaks tokens and confuses the agent. Keyed
    overwrites let the agent maintain a compact, current world model.

Why not just RAG with a vector store?
    v0 is corpus-of-twenty-notes. Substring match is fine; embedding lookup
    adds latency and a model dep without measurable improvement at this scale.
    The interface (`recall(query)`) is forward-compatible — swap the impl
    later without skill API churn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Journal:
    """Per-rollout note store. Lives in state["journal"]."""
    notes: dict[str, str] = field(default_factory=dict)
    objective: Optional[str] = None

    def add_note(self, key: str, text: str) -> str:
        """Write or overwrite a note. Returns a confirmation string."""
        key = key.strip().lower()
        if not key:
            return "Refused: empty note key."
        prev = self.notes.get(key)
        self.notes[key] = text.strip()
        return f"Note '{key}' {'updated' if prev else 'added'}."

    def recall(self, query: str) -> list[tuple[str, str]]:
        """Return (key, text) pairs whose key or text contains the query.

        Includes the pinned objective under key 'objective' so queries
        like `recall("objective")` or `recall("descend")` find the
        top-level goal (which would otherwise only render in the
        journal block, not show up in recall results)."""
        q = query.strip().lower()
        items = list(self.notes.items())
        if self.objective:
            items = [("objective", self.objective)] + items
        if not q:
            return items
        return [(k, t) for k, t in items if q in k.lower() or q in t.lower()]

    def pin_objective(self, text: str) -> str:
        prev = self.objective
        self.objective = text.strip()
        return f"Objective {'updated' if prev else 'set'}: {self.objective}"

    def render(self, max_chars: int = 2000) -> str:
        """Render the journal as a block of text for inclusion in observations.

        Capped at `max_chars` to bound per-turn token cost. The journal is
        re-emitted every turn; without a cap, a long rollout that writes
        many notes (or many belief_state:tN summaries) would blow the
        per-turn payload past useful sizes. When the cap fires, MOST
        RECENT notes (last-in dict order) and any `belief_state:` notes
        are kept; older arbitrary notes get dropped behind an elision
        marker. Objective is always preserved.
        """
        lines = []
        if self.objective:
            lines.append(f"Objective: {self.objective}")
        if self.notes:
            if lines:
                lines.append("")
            lines.append("Your notes:")
            # Two passes so we can fit within max_chars while keeping the
            # objective + most-recent notes. Belief-state notes are pinned
            # because they ARE the long-term memory.
            note_lines: list[str] = []
            kept: list[tuple[str, str]] = []
            dropped = 0
            items = list(self.notes.items())
            # Walk newest -> oldest, accumulating; pin belief_state.
            for k, t in reversed(items):
                line = f"  - {k}: {t}"
                tentative_len = sum(len(l) + 1 for l in lines + note_lines + [line])
                if tentative_len <= max_chars or k.startswith("belief_state:"):
                    note_lines.insert(0, line)  # preserve original order
                    kept.append((k, t))
                else:
                    dropped += 1
            if dropped:
                note_lines.insert(0, f"  - [elided {dropped} older notes; use `recall` to retrieve]")
            lines.extend(note_lines)
        return "\n".join(lines) if lines else ""

    def is_empty(self) -> bool:
        return not self.notes and not self.objective
