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


def build_nested(path: tuple[str, ...], value: Any) -> dict[str, Any]:
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


def json_tokens(value: Any) -> int:
    """JSON tokens in a value: every object, array, key and scalar counts once.

    The way a Neumann KH 120 II counts a request against its 29-token limit
    (measured: a set of a 20-entry list four levels deep is exactly 29).
    """
    if isinstance(value, dict):
        return 1 + sum(1 + json_tokens(child) for child in value.values())
    if isinstance(value, list):
        return 1 + sum(json_tokens(child) for child in value)
    return 1


def nesting_exceeds(value: Any, limit: int) -> bool:
    """Whether a parsed JSON value nests deeper than `limit`.

    Iterative on purpose: json.loads accepts objects nested far past the
    recursion limit, and every recursive walk after it (deep_merge, the
    error parser) then raised RecursionError on a reply from faulty firmware.
    """
    pending = [(value, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > limit:
            return True
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
    return False


def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
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


def extract(data: dict[str, Any], path: tuple[str, ...]) -> Any:
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
