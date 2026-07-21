"""Typed structured observation (flat feature-layer dataclass) + its schema."""
from __future__ import annotations
from dataclasses import dataclass, fields
from typing import Any, Optional


@dataclass
class Observation:
    player: Optional[tuple]   # (x, y)
    entities: list            # nethack_core.map_model.Entity
    grid: str                 # RLE topology
    status: dict
    inventory: list
    character: dict

    @classmethod
    def from_raw(cls, raw_obs, *, status, inventory, character):
        from nethack_core import build_map_model
        m = build_map_model(raw_obs)
        return cls(player=m.player, entities=m.entities, grid=m.grid,
                   status=dict(status or {}), inventory=list(inventory or []),
                   character=dict(character or {}))


def observation_spec() -> dict:
    """Declared schema: field name -> type name (dataclass introspection)."""
    return {f.name: (f.type if isinstance(f.type, str) else getattr(f.type, "__name__", str(f.type)))
            for f in fields(Observation)}
