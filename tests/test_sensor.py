"""Tests for what a sensor puts into the Home Assistant state.

A state is stored in the recorder and compared against by automations, so it
has to mean the same thing regardless of the interface language.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.sensor import (
    COMMON_SENSOR_DESCRIPTIONS,
    NON_SUBWOOFER_SENSOR_DESCRIPTIONS,
    SUBWOOFER_SENSOR_DESCRIPTIONS,
    NeumannKHSensor,
)

_COMPONENT = Path(__file__).parent.parent / "custom_components" / "neumann_kh"


def _description(key):
    for description in (
        *COMMON_SENSOR_DESCRIPTIONS,
        *NON_SUBWOOFER_SENSOR_DESCRIPTIONS,
        *SUBWOOFER_SENSOR_DESCRIPTIONS,
    ):
        if description.key == key:
            return description
    raise AssertionError(f"no sensor description for {key}")


def _sensor(key, value, language="de"):
    """Build a sensor around a stub coordinator - no Home Assistant needed."""
    description = _description(key)
    coordinator = SimpleNamespace(
        data={},
        host="fe80::1",
        value=lambda path: value,
        async_add_listener=lambda *args, **kwargs: None,
        model="KH 750",
    )
    entry = SimpleNamespace(
        entry_id="entry1",
        title="KH 750",
        data={"serial": "SIM0007500", "model": "KH 750", "host": "fe80::1"},
    )
    sensor = NeumannKHSensor(coordinator, entry, description)
    sensor.hass = SimpleNamespace(config=SimpleNamespace(language=language))
    return sensor


@pytest.mark.parametrize("key", ["out1_loudspeaker", "out2_loudspeaker"])
def test_an_unassigned_output_reports_the_raw_value(key):
    """The state used to be the translated text, which the recorder then kept.

    Switching the interface language would have split the history in two and
    broken every automation comparing against the old wording.
    """
    assert _sensor(key, "UNKNOWN", language="de").native_value == "UNKNOWN"
    assert _sensor(key, "UNKNOWN", language="en").native_value == "UNKNOWN"


@pytest.mark.parametrize("key", ["out1_loudspeaker", "out2_loudspeaker"])
def test_the_unassigned_state_is_translated_for_display(key):
    """Raw state, translated presentation - both languages have to carry it."""
    for name, expected in (
        ("strings.json", "Not assigned"),
        ("translations/en.json", "Not assigned"),
        ("translations/de.json", "Nicht zugewiesen"),
    ):
        data = json.loads((_COMPONENT / name).read_text(encoding="utf-8"))
        states = data["entity"]["sensor"][key].get("state", {})
        assert states.get("UNKNOWN") == expected, f"{name} is missing the state text"


def test_an_assigned_loudspeaker_passes_through_unchanged():
    """The device reports model names here; the set is open, so nothing maps."""
    assert _sensor("out1_loudspeaker", "KH 120 II").native_value == "KH 120 II"
