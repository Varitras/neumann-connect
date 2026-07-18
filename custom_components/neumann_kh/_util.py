"""Shared helper functions for nested SSC JSON structures."""

from __future__ import annotations

from typing import Any


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
    """Merge two nested dicts (in-place); source wins on conflicts."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
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
    notifications, dynamic labels); see the localisation notes in the README.
    """
    return de if (language or "en").startswith("de") else en
