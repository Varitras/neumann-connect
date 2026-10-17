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

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh import _async_relocate
from custom_components.neumann_kh.const import (
    CONF_FIRMWARE_VERSION,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
    FALLBACK_MODEL,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_OUTPUT_LEVEL,
)
from custom_components.neumann_kh.ssc_client import SSCDeviceError, SSCTimeoutError
from custom_components.neumann_kh.discovery import DiscoveredSpeaker

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


def _own_speaker(answer_for_other_paths=None, product="KH 120 II"):
    """A client whose device carries the entry's serial and model.

    Setup verifies the serial before the first poll, so a fake that answers
    the same thing for every path would be refused as a different speaker.
    """
    answers = {PATH_IDENTITY_SERIAL: _SERIAL, PATH_IDENTITY_PRODUCT: product}

    async def _get(path, **_):
        answer = answers.get(path, answer_for_other_paths)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = AsyncMock()
    client.get = AsyncMock(side_effect=_get)
    client.close = AsyncMock()
    return client


def _found(host=_NEW_HOST, port=45):
    return [DiscoveredSpeaker(mdns_name="KH120-SIMULATED._ssc._tcp.local.", host=host, port=port)]


async def _run(hass, entry, speakers, serial_answer):
    client = AsyncMock()
    client.get = AsyncMock(return_value=serial_answer)
    client.close = AsyncMock()
    with (
        patch(
            "custom_components.neumann_kh.async_scan_for_speakers",
            return_value=speakers,
        ),
        patch("custom_components.neumann_kh.SSCClient", return_value=client),
    ):
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

    with (
        patch("custom_components.neumann_kh.SSCClient", return_value=_own_speaker()),
        patch(
            "custom_components.neumann_kh.NeumannKHCoordinator.async_config_entry_first_refresh",
            side_effect=ConfigEntryNotReady("device offline"),
        ),
        patch("custom_components.neumann_kh._async_relocate", return_value=False) as relocate,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is False
        await hass.async_block_till_done()

    assert relocate.called, "a failed setup did not search for the speaker"
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_working_setup_does_not_search(hass, _custom_integration):
    """The scan costs four seconds - it must not run when nothing is wrong."""
    entry = _entry(hass)

    with (
        patch("custom_components.neumann_kh.SSCClient", return_value=_own_speaker()),
        patch(
            "custom_components.neumann_kh.NeumannKHCoordinator.async_config_entry_first_refresh",
            return_value=None,
        ),
        patch("custom_components.neumann_kh._async_relocate", return_value=False) as relocate,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

    assert not relocate.called


async def test_a_speaker_that_only_changed_port_is_followed(hass, _custom_integration):
    """Same address, different port - exactly what this repair is for.

    Comparing the address alone treated that as "nothing to do", so the entry
    kept retrying against the old port for good.
    """
    entry = _entry(hass)

    assert await _run(hass, entry, _found(host=_OLD_HOST, port=4545), _SERIAL) is True
    assert entry.data[CONF_HOST] == _OLD_HOST
    assert entry.data[CONF_PORT] == 4545


# --- Firmware version -------------------------------------------------------


async def _run_setup(hass, entry, version, stored=None, product="KH 120 II"):
    """Drive a successful setup with a client reporting `version`."""
    if stored is not None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FIRMWARE_VERSION: stored}
        )
    client = _own_speaker(answer_for_other_paths=version, product=product)
    with (
        patch(
            "custom_components.neumann_kh.NeumannKHCoordinator.async_config_entry_first_refresh",
            return_value=None,
        ),
        patch("custom_components.neumann_kh.SSCClient", return_value=client),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()
    return client


async def test_a_firmware_update_is_picked_up(hass, _custom_integration):
    """The version was only ever read while adding the entry.

    After updating a speaker the device info kept advertising whatever was
    installed back then.
    """
    entry = _entry(hass)

    await _run_setup(hass, entry, version="2_0_0", stored="1_7_3")

    assert entry.data[CONF_FIRMWARE_VERSION] == "2_0_0"


async def test_an_unchanged_firmware_version_is_not_rewritten(hass, _custom_integration):
    """Every rewrite stores the entry and notifies its listeners - for nothing."""
    entry = _entry(hass)

    await _run_setup(hass, entry, version="1_7_3", stored="1_7_3")
    before = dict(entry.data)

    # A second setup must not touch the entry either.
    await hass.config_entries.async_unload(entry.entry_id)
    await _run_setup(hass, entry, version="1_7_3")

    assert dict(entry.data) == before
    assert entry.data[CONF_FIRMWARE_VERSION] == "1_7_3"


@pytest.mark.parametrize("answered", [" 1_7_3 ", ["1_7_3"], True])
async def test_an_odd_firmware_answer_does_not_overwrite_the_version(
    hass, _custom_integration, answered
):
    """Padding or a non-text answer must not land in the device info.

    A list or a bool used to be stored as its Python repr, padding as-is.
    """
    entry = _entry(hass)

    await _run_setup(hass, entry, version=answered, stored="1_7_3")

    assert entry.data[CONF_FIRMWARE_VERSION] == "1_7_3"


async def test_a_model_stored_as_the_fallback_is_corrected_at_setup(hass, _custom_integration):
    """A product answer missing while adding the entry stored the fallback for good.

    A KH 750 then ran as a monitor forever: no subwoofer entities, the wrong
    poll paths and EQ containers.
    """
    entry = _entry(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MODEL: FALLBACK_MODEL})

    client = await _run_setup(hass, entry, version="2_1_2", product="KH 750")

    assert entry.data[CONF_MODEL] == "KH 750"
    assert entry.runtime_data.model == "KH 750"
    # The out5 detection runs for subwoofers only, so it has to see the
    # corrected model, not the fallback.
    asked = [call.args[0] for call in client.get.call_args_list]
    assert PATH_OUTPUT_LEVEL in asked
    assert asked.index(PATH_IDENTITY_PRODUCT) < asked.index(PATH_OUTPUT_LEVEL)


@pytest.mark.parametrize(
    "error", [SSCDeviceError("rejected", code=404), SSCTimeoutError("no answer")]
)
async def test_a_failed_product_read_still_refreshes_the_firmware(
    hass, _custom_integration, error
):
    entry = _entry(hass)

    await _run_setup(hass, entry, version="2_1_2", stored="1_7_3", product=error)

    assert entry.data[CONF_FIRMWARE_VERSION] == "2_1_2"
    assert entry.data[CONF_MODEL] == "KH 120 II"


@pytest.mark.parametrize("answered", [None, "", ["KH 750"]])
async def test_an_unusable_product_answer_keeps_the_stored_model(
    hass, _custom_integration, answered
):
    entry = _entry(hass)

    await _run_setup(hass, entry, version="2_1_2", product=answered)

    assert entry.data[CONF_MODEL] == "KH 120 II"


async def test_silent_candidates_are_asked_concurrently(hass, _custom_integration):
    """One after another this cost a connection timeout per silent candidate.

    A segment with a handful of stale announcements then held the repair for
    minutes - on every failed setup retry. Counted rather than timed: a wall
    clock limit failed under load although the queries did overlap.
    """
    import asyncio

    entry = _entry(hass)
    running = 0
    peak = 0
    found = [
        DiscoveredSpeaker(mdns_name=f"s{i}._ssc._tcp.local.", host=f"fe80::{i}%2", port=45)
        for i in range(8)
    ]

    class _SlowClient:
        """Every candidate takes a while and none of them answers usefully."""

        def __init__(self, *args, **kwargs):  # skipcq: PTC-W0049 - a stand-in, not a design
            pass

        async def get(self, path):  # skipcq: PYL-R0201 - a stand-in, not a design
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0)
            running -= 1
            return "SIM0009999"  # never the entry's serial

        async def close(self):  # skipcq: PYL-R0201 - a stand-in, not a design
            return None

    with (
        patch("custom_components.neumann_kh.async_scan_for_speakers", return_value=found),
        patch("custom_components.neumann_kh.SSCClient", _SlowClient),
    ):
        assert await _async_relocate(hass, entry) is False

    assert peak > 1, "the candidates were queried one after another"
