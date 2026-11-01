"""The three translation files stay in step.

`strings.json` is the source; `translations/en.json` is a copy of it, and
forgetting the copy was the recurring mistake of this project. German has to
carry every key English has, or the UI shows a raw key.
"""

from __future__ import annotations

import ast
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


def _exception_keys_used(source: str) -> set[str]:
    """Every literal key handed to an error, directly or on its way there.

    translation_key= on an *Error call, rejected_key= (passed on to one),
    the default of a rejected_key parameter and the first argument of _stop().
    Keys built at run time are not literals and are out of reach here.
    """
    used: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            for keyword in node.keywords:
                literal = isinstance(keyword.value, ast.Constant)
                if literal and keyword.arg == "rejected_key":
                    used.add(keyword.value.value)
                if literal and keyword.arg == "translation_key" and name.endswith("Error"):
                    used.add(keyword.value.value)
            if name == "_stop" and node.args and isinstance(node.args[0], ast.Constant):
                used.add(node.args[0].value)
        if isinstance(node, ast.arguments):
            params = node.args[len(node.args) - len(node.defaults) :]
            for param, default in zip(params, node.defaults, strict=True):
                if param.arg == "rejected_key" and isinstance(default, ast.Constant):
                    used.add(default.value)
    return used


def test_every_error_key_in_the_code_has_a_text():
    """Unit tests compare a key with a literal they repeat, never with strings.json.

    A typo, or a new key without an entry, stayed green everywhere and showed
    the raw key to the user.
    """
    known = set(_load("strings.json")["exceptions"])
    used = set().union(
        *(_exception_keys_used(path.read_text(encoding="utf-8")) for path in COMPONENT.glob("*.py"))
    )
    assert used, "the scan found no key at all - it went blind"
    assert not used - known, f"error key(s) without a text: {sorted(used - known)}"


def test_the_key_scan_sees_each_way_a_key_travels():
    """Counter-check: an invented key in each form is found."""
    source = """
raise HomeAssistantError(translation_domain=DOMAIN, translation_key="direct_key")
await self._async_write(path, value, rejected_key="passed_key")
raise _stop("stopped_key")
async def _async_write(self, path, value, rejected_key="default_key"): ...
"""
    assert _exception_keys_used(source) == {
        "direct_key",
        "passed_key",
        "stopped_key",
        "default_key",
    }
