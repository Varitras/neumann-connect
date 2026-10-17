"""Shared helper functions for SSC JSON values and nested structures."""

from __future__ import annotations

import math
from typing import Any


def finite_float(value: Any) -> float | None:
    """A device value as a finite float, or None if it is not one.

    SSC answers are plain JSON, so a number can arrive as text, as NaN or as
    an integer too large for a float - float() raises OverflowError for that,
    which no caller expected. One owner, so every reader treats them alike.
    """
    try:
        number = float(value)
    except ValueError, TypeError, OverflowError:
        return None
    if not math.isfinite(number):
        return None
    return number


def build_nested(path: tuple[str, ...], value: Any) -> dict:
    """Build a nested JSON object from a path tuple and a value.

    Example: build_nested(("audio", "out", "mute"), True)
             -> {"audio": {"out": {"mute": True}}}
    """
    node: dict[str, Any] = {}
    root = node
    for part in path[:-1]:
        node[part] = {}
        node = node[part]
    node[path[-1]] = value
    return root


def deep_merge(target: dict, source: dict) -> None:
    """Merge two nested dicts (in-place); source wins on conflicts.

    Nested dicts are copied, never shared: the coordinator merges its slow
    cache into each published snapshot, and a shared subtree let a later write
    to that snapshot reach back into the cache.
    """
    for key, value in source.items():
        if isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            deep_merge(target[key], value)
        else:
            target[key] = value


def extract(data: dict, path: tuple[str, ...]) -> Any:
    """Read a value from a nested dict using a path tuple."""
    node: Any = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def localized(language: str | None, de: str, en: str) -> str:
    """Pick the German or English text for a Home Assistant UI language.

    For messages that have no translation_key mechanism (persistent
    notifications, dynamic labels). Anything else uses translation keys.
    """
    return de if (language or "en").startswith("de") else en
