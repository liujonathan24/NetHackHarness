"""Raw NLE action-index escape hatch.

The *typed* Action set (``Action`` + ``action_spec()``) is derived from the skill
registry, which lives in the Hub — so it lives in the Hub too, at
``nethack_harness.interface``. The engine stays a pure substrate: only the raw
index escape hatch is defined here.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RawAction:
    index: int
