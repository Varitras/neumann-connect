"""Tests for the address self-repair after a failed setup.

A stored global IPv6 address dies with the next ISP prefix change, after which
the entry retries into the void every ten minutes. Home Assistant's zeroconf
discovery eventually fixes that too, but only when the pointer record is
refreshed - measured at roughly an hour. This path shortens it to the next
setup retry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.exceptions import ConfigEntryNotReady  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.neumann_kh import _async_relocate  # noqa: E402
from custom_components.neumann_kh.const import (  # noqa: E402
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
)
from custom_components.neumann_kh.discovery import DiscoveredSpeaker  # noqa: E402

_SERIAL = "SIM0001234"
_OLD_HOST = "2003:db8:old::1"
_NEW_HOST = "fe80::2%2"


@pytest.fixture
def _custom_integration(enable_custom_integrations, mock_async_zeroconf):
    yield


def _entry(hass, serial=_SERIAL, host=_OLD_HOST) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KH 120 II Right",
        unique_id=serial or "no-serial",
        data={
            CONF_HOST: host,
            CONF_PORT: 45,
            CONF_INTERFACE: "eth0",
            CONF_MODEL: "KH 120 II",
            **({CONF_SERIAL: serial} if serial else {}),
        },
    )
    entry.add_to_hass(hass)
    return entry


def _found(host=_NEW_HOST, port=45):
    return [DiscoveredSpeaker(mdns_name="KH120 II Right._ssc._tcp.local.", host=host, port=port)]


async def _run(hass, entry, speakers, serial_answer):
    client = AsyncMock()
    client.get = AsyncMock(return_value=serial_answer)
    client.close = AsyncMock()
    with patch(
        "custom_components.neumann_kh.async_scan_for_speakers",
        return_value=speakers,
    ), patch("custom_components.neumann_kh.SSCClient", return_value=client):
        return await _async_relocate(hass, entry)


async def test_moved_speaker_is_followed(hass, _custom_integration):
    entry = _entry(hass)

    assert await _run(hass, entry, _found(), _SERIAL) is True
    assert entry.data[CONF_HOST] == _NEW_HOST
    # The scope ID is inside the address, so the separate field is cleared.
    assert entry.data[CONF_INTERFACE] == ""
    # Same entry - entity IDs and history survive.
    assert entry.unique_id == _SERIAL


async def test_a_different_speaker_is_not_adopted(hass, _custom_integration):
    """Following the wrong unit would graft its readings onto this entry."""
    entry = _entry(hass)

    assert await _run(hass, entry, _found(), "SIM0007500") is False
    assert entry.data[CONF_HOST] == _OLD_HOST


async def test_entry_without_a_serial_is_left_alone(hass, _custom_integration):
    """Nothing to match against, so any match would be a guess."""
    entry = _entry(hass, serial=None)

    assert await _run(hass, entry, _found(), _SERIAL) is False
    assert entry.data[CONF_HOST] == _OLD_HOST


async def test_same_address_is_not_rewritten(hass, _custom_integration):
    """Rewriting it would schedule a reload that changes nothing."""
    entry = _entry(hass)

    assert await _run(hass, entry, _found(host=_OLD_HOST), _SERIAL) is False
    assert entry.data[CONF_HOST] == _OLD_HOST


async def test_nothing_found_is_not_an_error(hass, _custom_integration):
    entry = _entry(hass)

    assert await _run(hass, entry, [], _SERIAL) is False
    assert entry.data[CONF_HOST] == _OLD_HOST


async def test_a_failing_scan_does_not_mask_the_setup_error(hass, _custom_integration):
    """The setup error is the one worth reporting; a scan is only a bonus."""
    entry = _entry(hass)

    with patch(
        "custom_components.neumann_kh.async_scan_for_speakers",
        side_effect=OSError("no multicast here"),
    ):
        assert await _async_relocate(hass, entry) is False
    assert entry.data[CONF_HOST] == _OLD_HOST


async def test_a_failed_setup_actually_triggers_the_search(hass, _custom_integration):
    """Wiring test: every test above calls _async_relocate directly.

    Removing the call from async_setup_entry leaves all of them green while
    the repair is dead in the field, so this pins the call itself down.
    """
    entry = _entry(hass)

    with patch(
        "custom_components.neumann_kh.NeumannKHCoordinator.async_config_entry_first_refresh",
        side_effect=ConfigEntryNotReady("device offline"),
    ), patch(
        "custom_components.neumann_kh._async_relocate", return_value=False
    ) as relocate:
        assert await hass.config_entries.async_setup(entry.entry_id) is False
        await hass.async_block_till_done()

    assert relocate.called, "a failed setup did not search for the speaker"
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_working_setup_does_not_search(hass, _custom_integration):
    """The scan costs four seconds - it must not run when nothing is wrong."""
    entry = _entry(hass)

    with patch(
        "custom_components.neumann_kh.NeumannKHCoordinator.async_config_entry_first_refresh",
        return_value=None,
    ), patch(
        "custom_components.neumann_kh._async_relocate", return_value=False
    ) as relocate:
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

    assert not relocate.called
