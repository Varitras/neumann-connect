"""Neumann KH (SSC) integration - entry point.

Per config entry (= one physical speaker), an SSCClient and a
DataUpdateCoordinator are created and stored in hass.data, so that the
platforms (number, select, switch, sensor, binary_sensor, button, text)
can access them.

Backup and device discovery run exclusively manually via the
corresponding buttons (see button.py), not automatically.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PATH_IDENTITY_SERIAL,
)
from .coordinator import NeumannKHCoordinator
from .discovery import async_scan_for_speakers
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

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
    except Exception:  # noqa: BLE001 - a failed scan must not mask the setup error
        _LOGGER.debug("Could not search for %s after a failed setup", entry.title, exc_info=True)
        return False

    for speaker in speakers:
        if speaker.host == entry.data.get(CONF_HOST):
            # Already where we looked, so the address is not the problem -
            # and rewriting it would schedule a reload that changes nothing.
            continue
        client = SSCClient(host=speaker.host, port=speaker.port, timeout=DEFAULT_TIMEOUT)
        try:
            found = await client.get(PATH_IDENTITY_SERIAL)
        except (SSCConnectionError, SSCTimeoutError, SSCDeviceError):
            continue
        finally:
            await client.close()

        if str(found) != str(serial):
            continue

        _LOGGER.info(
            "Speaker %s answers at %s now instead of %s, updating the entry",
            entry.title,
            speaker.host,
            entry.data.get(CONF_HOST),
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one speaker)."""
    client = SSCClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        interface=entry.data.get(CONF_INTERFACE) or None,
        timeout=DEFAULT_TIMEOUT,
    )

    coordinator = NeumannKHCoordinator(
        hass, client, entry.title, model=entry.data.get(CONF_MODEL)
    )
    try:
        await coordinator.async_config_entry_first_refresh()
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # A platform failing to set up leaves async_unload_entry unreached, so
        # nothing else would close the socket or drop the coordinator - the
        # next setup attempt would stack another one on top.
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await client.close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and close the TCP connection cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator: NeumannKHCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        # Always close the connection, regardless of the platform unload result.
        await coordinator.client.close()
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok

