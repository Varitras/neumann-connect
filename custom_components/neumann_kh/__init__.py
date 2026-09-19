"""Neumann KH (SSC) integration - entry point.

Per config entry (= one physical speaker), an SSCClient and a
DataUpdateCoordinator are created and stored on the config entry, so that the
platforms (number, select, switch, sensor, binary_sensor, button, text)
can access them.

Backup and device discovery run exclusively manually via the
corresponding buttons (see button.py), not automatically.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    MAX_PARALLEL_IDENTITY_QUERIES,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VERSION,
)
from .coordinator import NeumannKHConfigEntry, NeumannKHCoordinator
from .discovery import async_scan_for_speakers
from .export_actions import mask_serial
from .identity import serial_matches
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError, mask_host

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.TEXT,
]


async def _async_relocate(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Look for this speaker on the network and store its current address.

    Runs only after a setup attempt already failed. A stored address can go
    stale on its own: a global IPv6 address carries the prefix the ISP
    delegates, and a forced reconnect hands out a new one, after which the
    entry retries into the void every ten minutes forever.

    Home Assistant's own zeroconf discovery covers this too, but not quickly:
    the speakers never announce unsolicited (measured), their address records
    live 120 s and are not refreshed on their own, so the address is only
    re-read when the pointer record is refreshed at 75 % of its 4500 s TTL -
    roughly an hour. This shortens that to the next setup retry.

    Returns True if the address changed, meaning a retry is worth it.
    """
    serial = entry.data.get(CONF_SERIAL)
    if not serial:
        # Entries created before serials were stored. Matching on anything
        # else would risk pointing this entry - and its history - at a
        # different speaker.
        return False

    try:
        speakers = await async_scan_for_speakers(hass)
    except Exception:
        _LOGGER.debug("Could not search for %s after a failed setup", entry.title, exc_info=True)
        return False

    # Already exactly where we looked means the address is not the problem -
    # and rewriting it would schedule a reload that changes nothing. The port
    # belongs in that comparison: a speaker that kept its address but moved to
    # another port is precisely the case this repair exists for.
    current = (entry.data.get(CONF_HOST), entry.data.get(CONF_PORT, DEFAULT_PORT))
    candidates = [s for s in speakers if (s.host, s.port) != current]

    # Asked concurrently, a few at a time. One after another this cost the
    # connection timeout per silent candidate, and this runs on every failed
    # setup retry.
    semaphore = asyncio.Semaphore(MAX_PARALLEL_IDENTITY_QUERIES)

    async def _serial_of(speaker):
        async with semaphore:
            client = SSCClient(host=speaker.host, port=speaker.port, timeout=DEFAULT_TIMEOUT)
            try:
                return await client.get(PATH_IDENTITY_SERIAL)
            except (SSCConnectionError, SSCTimeoutError, SSCDeviceError):
                return None
            finally:
                await client.close()

    found_serials = await asyncio.gather(*(_serial_of(s) for s in candidates))

    for speaker, found in zip(candidates, found_serials, strict=True):
        if not serial_matches(serial, found):
            continue

        _LOGGER.info(
            "Speaker %s answers at %s now instead of %s, updating the entry",
            entry.title,
            mask_host(speaker.host),
            mask_host(str(entry.data.get(CONF_HOST))),
        )
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_HOST: speaker.host,
                CONF_PORT: speaker.port,
                # The scope ID travels inside a discovered link-local address,
                # so a separately stored interface would contradict it.
                CONF_INTERFACE: "" if "%" in speaker.host else entry.data.get(CONF_INTERFACE, ""),
            },
        )
        return True

    return False


async def _async_refresh_firmware_version(
    hass: HomeAssistant, entry: ConfigEntry, client: SSCClient
) -> None:
    """Store the firmware version the speaker reports right now.

    It is otherwise only read while adding or reconfiguring the entry, so the
    version shown in the device info kept describing whatever was installed
    back then.

    Once per setup is not the same as "always current": a speaker that reboots
    while Home Assistant is running does not make the entry reload - the poll
    cycle simply fails a few times and picks up again. The version therefore
    stays stale until the entry is reloaded or Home Assistant restarts. Polling
    it every cycle to close that gap would cost a request per cycle for a value
    that changes once a year.

    Only written when it actually differs: an update rewrites the entry, and
    rewriting it on every start would reload the entry on every start.
    """
    try:
        version = await client.get(PATH_IDENTITY_VERSION)
    except Exception:
        # Deliberately broad. This is a cosmetic detail of the device info, so
        # nothing it can throw may take down a setup that otherwise succeeded -
        # the previously stored value simply stays.
        _LOGGER.debug("Could not read the firmware version of %s", entry.title, exc_info=True)
        return

    version = str(version) if version is not None else ""
    if not version or version == entry.data.get(CONF_FIRMWARE_VERSION):
        return

    _LOGGER.info(
        "%s reports firmware %s now instead of %s",
        entry.title,
        version,
        entry.data.get(CONF_FIRMWARE_VERSION) or "an unknown version",
    )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_FIRMWARE_VERSION: version}
    )


async def _async_verify_identity(entry: ConfigEntry, client: SSCClient) -> None:
    """Refuse to run an entry against a device that is not its speaker.

    Relocate, reconfigure and zeroconf all compared serials; the regular setup
    - the path every restart takes - never did. An address handed to another
    SSC device kept the entry running under its old identity, and a restore or
    a confirmed factory reset would have hit the wrong speaker. Checked before
    the first poll, so nothing of the stranger's state is ever published.

    Entries created before serials were stored cannot be checked; relocate
    skips those for the same reason.
    """
    expected = entry.data.get(CONF_SERIAL)
    if not expected:
        return
    try:
        answered = await client.get(PATH_IDENTITY_SERIAL)
    except (SSCConnectionError, SSCTimeoutError, SSCDeviceError) as err:
        raise ConfigEntryNotReady(f"Could not read the serial of {entry.title}: {err}") from err
    if not serial_matches(expected, answered):
        raise ConfigEntryNotReady(
            f"{entry.title} expected serial {mask_serial(str(expected))} but the device at "
            f"its address answered {mask_serial(str(answered))}"
        )


async def async_setup_entry(hass: HomeAssistant, entry: NeumannKHConfigEntry) -> bool:
    """Set up a config entry (one speaker)."""
    client = SSCClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        interface=entry.data.get(CONF_INTERFACE) or None,
        timeout=DEFAULT_TIMEOUT,
    )

    coordinator = NeumannKHCoordinator(hass, client, entry.title, model=entry.data.get(CONF_MODEL))
    try:
        await _async_verify_identity(entry, client)
        await coordinator.async_config_entry_first_refresh()
    except asyncio.CancelledError:
        # `except Exception` does not catch this - CancelledError derives from
        # BaseException so a cancellation cannot be swallowed by accident - so
        # a setup cancelled rather than failed used to walk straight past the
        # cleanup below and leave the socket open. Not a failed setup, so no
        # relocate: just give the connection back.
        await client.close()
        raise
    except Exception:
        # Setup fails (e.g. ConfigEntryNotReady with a powered-off
        # device): close the open socket. HA retries the setup later
        # with a new client - without close() half-open connections
        # would accumulate until then.
        await client.close()
        # The speaker may simply have moved to a different address. Correcting
        # it here means the retry that HA has already scheduled finds it,
        # instead of the entry failing every ten minutes indefinitely.
        await _async_relocate(hass, entry)
        raise

    await _async_refresh_firmware_version(hass, entry, client)

    entry.runtime_data = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except asyncio.CancelledError:
        await client.close()
        raise
    except Exception:
        # A platform failing to set up leaves async_unload_entry unreached, so
        # nothing else would close the socket. The coordinator needs no undoing
        # any more: it lives on the entry, and the next attempt overwrites it.
        await client.close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeumannKHConfigEntry) -> bool:
    """Unload a config entry and close the TCP connection cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Always close the connection, regardless of the platform unload result.
    # Guarded because a setup that failed before reaching the assignment leaves
    # the entry without one, and Home Assistant still unloads it.
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None:
        await coordinator.client.close()

    return unload_ok
