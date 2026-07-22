"""PySC2-style interface to NetHack over nethack_core (RL-ready) — raw substrate.

Exposes a typed :class:`Observation` and :class:`RawAction` (bare NLE index)
stepping via :class:`NetHackInterface`. This package has **no** dependency on the
Hub. The typed ``Action`` set + skill dispatch + ``action_spec()`` are derived
from the Hub's skill registry and live in the Hub at
``nethack_harness.interface`` (import ``Action``/``action_spec``/
``TypedNetHackInterface`` from there).
"""
__version__ = "0.0.1"

from nethack_interface.observation import Observation, observation_spec  # noqa: E402
from nethack_interface.actions import RawAction                          # noqa: E402
from nethack_interface.env import NetHackInterface                        # noqa: E402

__all__ = ["Observation", "observation_spec", "RawAction", "NetHackInterface"]
