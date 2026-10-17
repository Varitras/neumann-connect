"""What every writable entity sends to the speaker, and what it does with the answer.

The write path used to be five hand-copied blocks (number, select, switch,
text, EQ switch). Each copy was correct, but none was tested, and a change to
the contract had to be made five times. These tests pin the contract for all
of them at once:

* the payload has the type the device itself reports (an int path gets an int);
* a rejection names the entity's own reason, a lost connection says so;
* an unconfirmed write - no echo, or the line dropped after sending - makes the
  next poll re-read the written path. Without that, a slow-polled value showed
  the old state for up to five minutes although the device had the new one;
* a non-finite number never leaves Home Assistant.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh.const import (
    DEFAULT_VENDOR,
    DOMAIN,
    PATH_DEVICE_NAME,
    PATH_IDENTIFY,
)
from custom_components.neumann_kh.eq import NeumannKHEQContainerSwitch
from custom_components.neumann_kh.eq_containers import NON_SUBWOOFER_EQ_CONTAINERS
from custom_components.neumann_kh.number import (
    BRIGHTNESS_DESCRIPTION,
    COMMON_NUMBER_DESCRIPTIONS,
    NeumannKHNumber,
    _build_output_delay_description,
)
from custom_components.neumann_kh.select import INPUT_INTERFACE_DESCRIPTION, NeumannKHSelect
from custom_components.neumann_kh.ssc_client import (
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
)
from custom_components.neumann_kh.switch import COMMON_SWITCH_DESCRIPTIONS, NeumannKHSwitch
from custom_components.neumann_kh.text import NeumannKHDeviceNameText

_ECHO = object()


class _Client:
    """Records every set; answers with an echo, None, or an exception."""

    def __init__(self, answer=_ECHO) -> None:
        self.answer = answer
        self.sent: list[tuple[tuple[str, ...], object]] = []

    async def set(self, path, value):
        self.sent.append((path, value))
        if isinstance(self.answer, Exception):
            raise self.answer
        if self.answer is _ECHO:
            return value
        return self.answer


class _Coordinator:
    def __init__(self, client: _Client, value=None) -> None:
        self.client = client
        self.data = {}
        self.confirmed: list[tuple[tuple[str, ...], object]] = []
        self.reread: list[tuple[str, ...]] = []
        self.persisted = 0
        self._value = value

    def value(self, path):
        return self._value

    def async_add_listener(self, *args, **kwargs):
        return lambda: None

    def apply_confirmed_value(self, path, value):
        self.confirmed.append((path, value))

    def request_reread(self, path):
        self.reread.append(path)

    async def async_persist(self):
        self.persisted += 1


def _entry(**data):
    return SimpleNamespace(entry_id="entry1", title="Left", data=data)


def _number(key, coordinator):
    descriptions = {d.key: d for d in COMMON_NUMBER_DESCRIPTIONS}
    descriptions[BRIGHTNESS_DESCRIPTION.key] = BRIGHTNESS_DESCRIPTION
    descriptions["output_delay"] = _build_output_delay_description(is_subwoofer=False)
    return NeumannKHNumber(coordinator, _entry(serial="SIM0001234"), descriptions[key])


def _switch(coordinator):
    mute = next(d for d in COMMON_SWITCH_DESCRIPTIONS if d.key == "mute")
    return NeumannKHSwitch(coordinator, _entry(serial="SIM0001234"), mute)


def _eq_switch(coordinator):
    return NeumannKHEQContainerSwitch(
        coordinator, _entry(serial="SIM0001234"), NON_SUBWOOFER_EQ_CONTAINERS[0]
    )


# (label, entity factory, write coroutine, expected path, expected payload)
WRITES = [
    (
        "level",
        lambda c: _number("output_level", c),
        lambda e: e.async_set_native_value(85.5),
        ("audio", "out", "level"),
        85.5,
    ),
    (
        "auto-standby-time",
        lambda c: _number("standby_auto_time", c),
        lambda e: e.async_set_native_value(30.0),
        ("device", "standby", "auto_standby_time"),
        30,
    ),
    (
        "standby-level",
        lambda c: _number("standby_level", c),
        lambda e: e.async_set_native_value(-70.0),
        ("device", "standby", "level"),
        -70,
    ),
    (
        "logo-brightness",
        lambda c: _number("logo_brightness", c),
        lambda e: e.async_set_native_value(50.0),
        ("ui", "logo", "brightness"),
        50,
    ),
    (
        "delay-rounds",
        lambda c: _number("output_delay", c),
        lambda e: e.async_set_native_value(99.6),
        ("audio", "out", "delay"),
        100,
    ),
    (
        "select",
        lambda c: NeumannKHSelect(c, _entry(serial="SIM0001234"), INPUT_INTERFACE_DESCRIPTION),
        lambda e: e.async_select_option("DIGITAL ONLY"),
        ("audio", "in", "interface"),
        "DIGITAL ONLY",
    ),
    ("switch", _switch, lambda e: e.async_turn_on(), ("audio", "out", "mute"), True),
    (
        "text",
        lambda c: NeumannKHDeviceNameText(c, _entry(serial="SIM0001234")),
        lambda e: e.async_set_value("Left"),
        PATH_DEVICE_NAME,
        "Left",
    ),
    (
        "eq-switch",
        _eq_switch,
        lambda e: e.async_turn_on(),
        NON_SUBWOOFER_EQ_CONTAINERS[0].path + ("enabled",),
        [True] * NON_SUBWOOFER_EQ_CONTAINERS[0].band_count,
    ),
]
IDS = [write[0] for write in WRITES]


@pytest.mark.parametrize(("label", "build", "write", "path", "payload"), WRITES, ids=IDS)
async def test_each_write_sends_the_payload_type_the_device_reports(
    label, build, write, path, payload
):
    coordinator = _Coordinator(_Client())
    await write(build(coordinator))

    assert coordinator.client.sent == [(path, payload)]
    assert type(coordinator.client.sent[0][1]) is type(payload)
    assert coordinator.confirmed == [(path, payload)]


REJECTION_KEYS = {
    "level": "change_rejected",
    "select": "selection_rejected",
    "switch": "change_rejected",
    "text": "name_rejected",
    "eq-switch": "change_rejected",
}


@pytest.mark.parametrize(
    ("label", "build", "write", "path", "payload"),
    [w for w in WRITES if w[0] in REJECTION_KEYS],
    ids=[w[0] for w in WRITES if w[0] in REJECTION_KEYS],
)
async def test_a_rejected_write_names_the_entity_specific_reason(
    label, build, write, path, payload
):
    coordinator = _Coordinator(_Client(SSCDeviceError("rejected")))
    with pytest.raises(HomeAssistantError) as caught:
        await write(build(coordinator))
    assert caught.value.translation_key == REJECTION_KEYS[label]
    assert coordinator.confirmed == []


@pytest.mark.parametrize(("label", "build", "write", "path", "payload"), WRITES, ids=IDS)
async def test_an_unconfirmed_write_rereads_the_written_path(label, build, write, path, payload):
    coordinator = _Coordinator(_Client(answer=None))
    await write(build(coordinator))

    assert coordinator.reread == [path]
    assert coordinator.confirmed == []


@pytest.mark.parametrize(
    "error", [SSCTimeoutError("t"), SSCConnectionError("c")], ids=["timeout", "dropped"]
)
async def test_a_write_lost_after_sending_rereads_the_path(error):
    coordinator = _Coordinator(_Client(error))
    with pytest.raises(HomeAssistantError) as caught:
        await _switch(coordinator).async_turn_on()
    assert caught.value.translation_key == "device_unreachable"
    assert coordinator.reread == [("audio", "out", "mute")]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
async def test_a_non_finite_number_is_never_sent(value):
    coordinator = _Coordinator(_Client())
    with pytest.raises(HomeAssistantError) as caught:
        await _number("output_level", coordinator).async_set_native_value(value)
    assert caught.value.translation_key == "invalid_number"
    assert coordinator.client.sent == []


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, "nan", "-inf", pytest.param(10**400, id="too-large-for-a-float")]
)
def test_a_non_finite_device_value_shows_as_unknown_in_a_number(value):
    assert _number("output_level", _Coordinator(_Client(), value)).native_value is None


def test_an_overlong_device_name_shows_as_unknown():
    text = NeumannKHDeviceNameText(_Coordinator(_Client(), "x" * 60), _entry(serial="SIM0001234"))
    assert text.native_value is None


def test_a_device_without_stored_identity_still_gets_a_complete_device_entry():
    """Entries from before serial, vendor and firmware were stored.

    An empty serial would put every such speaker under the same identifier
    (DOMAIN, "") and merge them into one device.
    """
    entity = NeumannKHDeviceNameText(
        _Coordinator(_Client()), _entry(serial="", vendor="", firmware_version="")
    )
    info = entity.device_info
    assert info["identifiers"] == {(DOMAIN, "entry1")}
    assert info["manufacturer"] == DEFAULT_VENDOR
    assert info["sw_version"] is None


async def test_the_entity_shows_what_the_device_confirmed_not_what_was_sent():
    """A device that clamps or rounds answers with its own value."""
    coordinator = _Coordinator(_Client(answer=80.0))
    await _number("output_level", coordinator).async_set_native_value(85.5)

    assert coordinator.confirmed == [(("audio", "out", "level"), 80.0)]


def test_the_coordinator_stub_only_models_methods_the_real_one_has():
    """A stub that defines the contract itself stays green when the real API moves."""
    import inspect

    from custom_components.neumann_kh.coordinator import NeumannKHCoordinator

    for name in (
        "value",
        "apply_confirmed_value",
        "request_reread",
        "async_add_listener",
        "async_persist",
    ):
        real = getattr(NeumannKHCoordinator, name)
        stub = getattr(_Coordinator, name)
        assert inspect.iscoroutinefunction(real) == inspect.iscoroutinefunction(stub), name


@pytest.mark.parametrize(("label", "build", "write", "path", "payload"), WRITES, ids=IDS)
async def test_every_accepted_write_is_persisted(label, build, write, path, payload):
    """The coordinator decides whether the model needs an explicit save."""
    coordinator = _Coordinator(_Client())
    await write(build(coordinator))
    assert coordinator.persisted == 1


@pytest.mark.parametrize("value", [True, False])
async def test_blinking_the_logo_is_not_persisted(value):
    """Identify is a momentary action, not a setting worth a flash write."""
    identify = next(d for d in COMMON_SWITCH_DESCRIPTIONS if d.key == "identify")
    coordinator = _Coordinator(_Client())
    switch = NeumannKHSwitch(coordinator, _entry(serial="SIM0001234"), identify)

    await (switch.async_turn_on() if value else switch.async_turn_off())

    assert coordinator.persisted == 0
    assert coordinator.client.sent == [(PATH_IDENTIFY, value)], "the blink itself must still go out"
    assert coordinator.confirmed == [(PATH_IDENTIFY, value)]


async def test_a_rejected_write_is_not_persisted():
    coordinator = _Coordinator(_Client(SSCDeviceError("rejected")))
    with pytest.raises(HomeAssistantError):
        await _switch(coordinator).async_turn_on()
    assert coordinator.persisted == 0


async def test_an_unconfirmed_write_is_persisted_too():
    """No echo does not mean the value did not land - it may need saving."""
    coordinator = _Coordinator(_Client(answer=None))
    await _switch(coordinator).async_turn_on()
    assert coordinator.persisted == 1


async def test_a_failed_save_keeps_the_confirmed_value_on_screen():
    """The value reached the device; only keeping it across power-off failed."""
    coordinator = _Coordinator(_Client())

    async def _save_fails():
        raise HomeAssistantError("not saved")

    coordinator.async_persist = _save_fails
    with pytest.raises(HomeAssistantError):
        await _switch(coordinator).async_turn_on()
    assert coordinator.confirmed == [(("audio", "out", "mute"), True)]
