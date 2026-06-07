"""Compose the per-turn user-message content.

The per-turn template returns either a string (text observation) or a multimodal
content list (image variants). ``compose_user_content`` injects the per-turn
prefix parts (autohalt / refiner / multi-tool / feedback notices) into either
shape so no prefix information is lost.
"""
from __future__ import annotations

from typing import Union

Content = Union[str, list]


def compose_user_content(obs: Content, prefix_parts: list) -> Content:
    """Wrap a string or multimodal-list observation, injecting prefix parts.

    String obs reproduce the legacy ``"\n".join(prefix) + "\n\n" + obs`` join.
    List obs get the prefix as a single leading ``{"type": "text"}`` block.
    """
    if isinstance(obs, str):
        if prefix_parts:
            return "\n".join(prefix_parts) + "\n\n" + obs
        return obs
    # multimodal content list
    if prefix_parts:
        return [{"type": "text", "text": "\n".join(prefix_parts)}, *obs]
    return obs


def content_to_text(obs: Content) -> str:
    """Extract the text form of a content value (for the trace writer)."""
    if isinstance(obs, str):
        return obs
    return next((p["text"] for p in obs if p.get("type") == "text"), "")
