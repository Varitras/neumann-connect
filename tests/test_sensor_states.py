"""The `not_assigned` state is declared in exactly one set of places.

The devices answer the literal string "UNKNOWN" in two meanings. On a
subwoofer output it means nothing is connected, and the integration turns it
into `not_assigned`, which reads as "Not assigned". Everywhere else it means
the device does not report the value - saying "Not assigned" about a hardware
version would be plain wrong, so those return no value and Home Assistant
shows its own translated "Unknown".

Which sensors belong to the first group therefore lives in two places: the set
in sensor.py and the state translations. This keeps them in step - adding a
third assignment sensor to only one of them fails here.

Measured against the hardware on 2026-09-02: of the seventeen text sensors,
out1_loudspeaker and out2_loudspeaker are the only ones a KH 120 II or KH 750
ever answers "UNKNOWN" for.
"""

from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import sensor as sensor_module

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"
STATE = "not_assigned"


def _translation_keys_with_the_state() -> set[str]:
    strings = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    sensors = strings.get("entity", {}).get("sensor", {})
    return {
        translation_key
        for translation_key, block in sensors.items()
        if STATE in block.get("state", {})
    }


def _descriptions():
    for name in dir(sensor_module):
        if name.endswith("SENSOR_DESCRIPTIONS"):
            yield from getattr(sensor_module, name)


def test_the_mapped_sensors_are_exactly_the_translated_ones():
    mapped = set(sensor_module._UNASSIGNED_KEYS)
    translated = _translation_keys_with_the_state()

    assert mapped == translated, (
        f"sensors mapped to {STATE}: {sorted(mapped)}, sensors with a {STATE} "
        f"text: {sorted(translated)}. A sensor in one list and not the other "
        "either shows an untranslated slug or silently loses the mapping."
    )


def test_every_mapped_sensor_exists_and_is_a_text_sensor():
    """A stale entry maps a key no sensor has, and nothing would say so."""
    by_key = {description.key: description for description in _descriptions()}
    unknown = sorted(set(sensor_module._UNASSIGNED_KEYS) - set(by_key))

    assert not unknown, f"mapped keys without a sensor: {unknown}"

    numeric = sorted(key for key in sensor_module._UNASSIGNED_KEYS if by_key[key].numeric)
    assert not numeric, (
        f"numeric sensor(s) in the mapping: {numeric} - the branch that reads "
        "it only runs for text sensors, so the entry would never take effect."
    )


def test_the_scan_sees_the_descriptions_at_all():
    """Proof-of-red: a renamed descriptions tuple would empty both checks."""
    keys = {description.key for description in _descriptions()}

    assert len(keys) > 10, f"only {len(keys)} sensor descriptions found - the scan is blind"
    assert "out1_loudspeaker" in keys
