"""A stored address that now belongs to a different speaker.

Relocate, reconfigure and zeroconf all compare the serial the device answers
with the one the entry stores. The regular setup - the path every restart
takes - never asked. An entry whose address had been handed to another SSC
device kept running under its old identity, and its entities, a restore and a
confirmed factory reset would have hit the wrong speaker.

The matrix: a stored serial with a device that answers the same one, a
different one, or nothing usable; and an entry that stores no serial at all
(created before serials were kept), which cannot be checked and is let through
exactly as relocate lets it through.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh.const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
    PATH_IDENTITY_SERIAL,
)

_SERIAL = "SIM0001234"
_OTHER_SERIAL = "SIM0009999"


@pytest.fixture
def _custom_integration(enable_custom_integrations, mock_async_zeroconf):
    yield


def _entry(hass, serial: str | None = _SERIAL) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KH 120 II Right",
        unique_id=serial or "fe80::2%2_45",
        data={
            CONF_HOST: "fe80::2%2",
            CONF_PORT: 45,
            CONF_INTERFACE: "eth0",
            CONF_MODEL: "KH 120 II",
            **({CONF_SERIAL: serial} if serial else {}),
        },
    )
    entry.add_to_hass(hass)
    return entry


class _SpeakerWithSerial:
    """Answers every path, and the identity path with the given serial."""

    def __init__(self, serial, **kwargs) -> None:
        self.serial = serial
        self.closed = False
        self.asked_for_serial = False
        self.priority_waiting = asyncio.Event()

    async def get(self, path, priority: bool = False):
        if path == PATH_IDENTITY_SERIAL:
            self.asked_for_serial = True
            return self.serial
        return 0.0

    async def set(self, path, value, priority: bool = False):
        return None

    async def close(self) -> None:
        await asyncio.sleep(0)
        self.closed = True


async def _set_up(hass, entry, client) -> tuple[bool, bool]:
    with (
        patch("custom_components.neumann_kh.SSCClient", return_value=client),
        patch("custom_components.neumann_kh._async_relocate", return_value=False) as relocate,
    ):
        loaded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return loaded, relocate.called


async def test_a_different_speaker_at_the_address_is_refused(hass, _custom_integration):
    entry = _entry(hass)
    client = _SpeakerWithSerial(_OTHER_SERIAL)

    loaded, relocated = await _set_up(hass, entry, client)

    assert not loaded, "an entry was set up against a speaker with another serial"
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert relocated, "the speaker presumably moved - the search for it did not run"
    assert client.closed


async def test_a_device_that_answers_no_serial_is_refused_too(hass, _custom_integration):
    """A known serial must be matched, not merely not contradicted."""
    entry = _entry(hass)
    client = _SpeakerWithSerial(None)

    loaded, _ = await _set_up(hass, entry, client)

    assert not loaded
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_the_right_speaker_still_loads(hass, _custom_integration):
    entry = _entry(hass)
    client = _SpeakerWithSerial(_SERIAL)

    loaded, relocated = await _set_up(hass, entry, client)

    assert loaded
    assert entry.state is ConfigEntryState.LOADED
    assert not relocated


async def test_an_entry_without_a_stored_serial_is_not_checked(hass, _custom_integration):
    """Nothing to compare against - and the check must not even be attempted."""
    entry = _entry(hass, serial=None)
    client = _SpeakerWithSerial(_OTHER_SERIAL)

    loaded, _ = await _set_up(hass, entry, client)

    assert loaded
    assert not client.asked_for_serial
