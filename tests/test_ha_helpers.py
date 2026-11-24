"""ha_helpers.py names the plugin that is broken, not the one that is not there."""

from __future__ import annotations

import builtins
import pathlib
import runpy

import pytest

HELPERS = pathlib.Path(__file__).with_name("ha_helpers.py")


def test_a_module_missing_inside_the_plugin_is_named(monkeypatch):
    """On native Windows fcntl is missing; the message blamed the other plugin."""
    real_import = builtins.__import__

    def without_fcntl(name, *args, **kwargs):
        if name.startswith("pytest_homeassistant"):
            raise ModuleNotFoundError("No module named 'fcntl'", name="fcntl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_fcntl)
    with pytest.raises(ModuleNotFoundError) as missing:
        runpy.run_path(str(HELPERS))
    assert missing.value.__context__ is None
