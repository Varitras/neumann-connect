"""Which device answers turn a problem sensor on.

Clip arrives as one bool per channel, warnings as one text per channel with
"NO_WARNING" as the normal state. An inverted mapping reads as "everything is
fine" during an actual clip, so each payload shape is pinned here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    SUBWOOFER_BINARY_SENSOR_DESCRIPTIONS,
    NeumannKHBinarySensor,
)


def _binary_sensor(key, value):
    description = next(
        description
        for description in (*BINARY_SENSOR_DESCRIPTIONS, *SUBWOOFER_BINARY_SENSOR_DESCRIPTIONS)
        if description.key == key
    )
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
    return NeumannKHBinarySensor(coordinator, entry, description)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("input_clip", [False, False], False),
        ("input_clip", [False, True], True),
        ("input_clip", True, True),
        ("input_clip", False, False),
        ("input_clip", None, None),
        ("warning", ["NO_WARNING", "NO_WARNING"], False),
        ("warning", ["NO_WARNING", "OVERTEMPERATURE"], True),
        ("warning", "NO_WARNING", False),
        ("warning", "OVERTEMPERATURE", True),
        ("warning", None, None),
        ("auto_standby", True, True),
        ("auto_standby", False, False),
    ],
)
def test_a_problem_sensor_is_on_exactly_when_the_device_reports_one(key, value, expected):
    assert _binary_sensor(key, value).is_on is expected
