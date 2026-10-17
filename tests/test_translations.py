"""The three translation files stay in step.

`strings.json` is the source; `translations/en.json` is a copy of it, and
forgetting the copy was the recurring mistake of this project. German has to
carry every key English has, or the UI shows a raw key.
"""

from __future__ import annotations

import json
import pathlib

COMPONENT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _keys(tree: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _keys(value, path) if isinstance(value, dict) else {path}
    return keys


def test_the_english_translation_is_the_source_verbatim():
    assert _load("translations/en.json") == _load("strings.json")


def test_german_has_exactly_the_keys_english_has():
    english = _keys(_load("strings.json"))
    german = _keys(_load("translations/de.json"))
    assert not english - german, f"missing in de.json: {sorted(english - german)}"
    assert not german - english, f"only in de.json: {sorted(german - english)}"


def test_a_setup_already_running_has_a_readable_reason():
    """Manual or scan setup while a discovery card for the same speaker is open.

    Home Assistant aborts with "already_in_progress"; without the key the
    dialog shows the raw identifier.
    """
    assert "already_in_progress" in _load("strings.json")["config"]["abort"]
