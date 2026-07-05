"""Gemeinsame Hilfsfunktionen für verschachtelte SSC-JSON-Strukturen.

Vorher waren `build_nested`/`deep_merge` sowohl in ssc_client.py als auch in
coordinator.py separat implementiert (Code-Duplikation) - jetzt an einer
Stelle, von beiden importiert.
"""

from __future__ import annotations

from typing import Any


def build_nested(path: tuple[str, ...], value: Any) -> dict:
    """Baut aus einem Pfad-Tupel und einem Wert ein verschachteltes JSON-Objekt.

    Beispiel: build_nested(("audio", "out", "mute"), True)
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
    """Führt zwei verschachtelte Dicts zusammen (in-place), source gewinnt bei Konflikten."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def extract(data: dict, path: tuple[str, ...]) -> Any:
    """Liest einen Wert aus einem verschachtelten Dict anhand eines Pfad-Tupels."""
    node: Any = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
