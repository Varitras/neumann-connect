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

from ._util import finite_float
from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    MAX_PARALLEL_IDENTITY_QUERIES,
    MODELS_WITH_SUBWOOFER_FEATURES,
    OUT5_OUTPUT_ALIASES,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VERSION,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_LEVEL_OUT5,
)
from .coordinator import NeumannKHConfigEntry, NeumannKHCoordinator
from .discovery import async_scan_for_speakers
from .identity import as_identity_text, mask_serial, serial_matches
from .ssc_client import (
    ERROR_NOT_FOUND,
    SSCClient,
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
    mask_host,
)

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
    entry retries into the void forever (every 80 s, from Home Assistant 2026.6
    every 10 minutes).

    Home Assistant's own zeroconf discovery covers this too, but not quickly:
    the speakers never announce unsolicited (measured), their address records
    live 120 s and are not refreshed on their own, so the address is only
    re-read when the pointer record is refreshed at 75 % of its 4500 s TTL -
    roughly an hour. This shortens that to the next setup retry.

    Returns whether the address changed. The setup does not need it - Home
    Assistant retries either way - but it is what the tests assert on.
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
    # and rewriting it would only cost a storage write and an update signal for
    # nothing. The port belongs in that comparison: a speaker that kept its
    # address but moved to another port is precisely the case this repair
    # exists for.
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


# Entry field and the path it is refreshed from at every setup.
_REFRESHED_IDENTITY = (
    (CONF_MODEL, PATH_IDENTITY_PRODUCT),
    (CONF_FIRMWARE_VERSION, PATH_IDENTITY_VERSION),
)


async def _async_refresh_identity(
    hass: HomeAssistant, entry: ConfigEntry, client: SSCClient
) -> None:
    """Store the model and firmware version the speaker reports right now.

    Both are otherwise only read while adding or reconfiguring the entry, so
    the device info kept describing whatever was installed back then - and a
    product answer missing at that moment left the fallback model stored for
    good, which runs a KH 750 without its subwoofer entities. Read before the
    coordinator is built, because the model decides what it polls.

    Once per setup is not the same as "always current": a speaker that reboots
    while Home Assistant is running does not make the entry reload - the poll
    cycle simply fails a few times and picks up again. The version therefore
    stays stale until the entry is reloaded or Home Assistant restarts. Polling
    it every cycle to close that gap would cost a request per cycle for a value
    that changes once a year.

    Only written when it actually differs: every update rewrites the stored
    entry and notifies its listeners, which is pointless when nothing changed.
    """
    changed = {}
    for key, path in _REFRESHED_IDENTITY:
        try:
            answered = await client.get(path)
        except Exception:
            # Deliberately broad. Nothing this can throw may take down a setup
            # that otherwise succeeds - the previously stored value stays.
            _LOGGER.debug("Could not read %s of %s", key, entry.title, exc_info=True)
            continue
        value = as_identity_text(answered)
        if not value or value == entry.data.get(key):
            continue
        _LOGGER.info(
            "%s reports %s %s now instead of %s",
            entry.title,
            key,
            value,
            entry.data.get(key) or "nothing",
        )
        changed[key] = value
    if changed:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **changed})


async def _async_answers_not_found(client: SSCClient, path: tuple[str, ...]) -> bool:
    """True only for an explicit 404 - silence, timeouts and other codes are not."""
    try:
        await client.get(path)
    except SSCDeviceError as err:
        return err.code == ERROR_NOT_FOUND
    except (SSCConnectionError, SSCTimeoutError):
        return False
    return False


async def _async_answers_a_number(client: SSCClient, path: tuple[str, ...]) -> bool:
    try:
        value = await client.get(path)
    except (SSCConnectionError, SSCTimeoutError, SSCDeviceError):
        return False
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return is_number and finite_float(value) is not None


async def _async_select_output_paths(entry: ConfigEntry, client: SSCClient) -> None:
    """Point level and mute at audio/out5 on a KH 750 that keeps them there.

    Only on a conclusive answer: audio/out/level must be a 404 and
    audio/out5/level a real number. Anything else - the speaker offline, a
    timeout, another error - keeps audio/out, the layout of current firmware.
    A setup retry asks again.
    """
    if entry.data.get(CONF_MODEL) not in MODELS_WITH_SUBWOOFER_FEATURES:
        return
    if not await _async_answers_not_found(client, PATH_OUTPUT_LEVEL):
        return
    if not await _async_answers_a_number(client, PATH_OUTPUT_LEVEL_OUT5):
        return
    _LOGGER.debug("%s keeps output level and mute in audio/out5", entry.title)
    client.use_path_aliases(OUT5_OUTPUT_ALIASES)


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
            f"{entry.title} expected serial {mask_serial(expected)} but the device at "
            f"its address answered {mask_serial(answered)}"
        )


async def async_setup_entry(hass: HomeAssistant, entry: NeumannKHConfigEntry) -> bool:
    """Set up a config entry (one speaker)."""
    client = SSCClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        interface=entry.data.get(CONF_INTERFACE) or None,
        timeout=DEFAULT_TIMEOUT,
    )

    try:
        await _async_verify_identity(entry, client)
        await _async_refresh_identity(hass, entry, client)
        await _async_select_output_paths(entry, client)
        coordinator = NeumannKHCoordinator(
            hass, client, entry.title, model=entry.data.get(CONF_MODEL)
        )
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
        # instead of the entry failing on every retry indefinitely.
        await _async_relocate(hass, entry)
        raise

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
