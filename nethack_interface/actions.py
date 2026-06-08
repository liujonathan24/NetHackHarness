"""Typed action set derived from the SkillRegistry (single source of truth)
plus a raw NLE action-index escape hatch."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class RawAction:
    index: int


def action_spec() -> dict:
    """name -> arg schema, sourced from the live skill registry (no drift)."""
    from nethack_harness.tools.skills import registry
    return dict(registry._schemas)
