"""Neumann KH (SSC) integration - entry point.

Per config entry (= one physical speaker), an SSCClient and a
DataUpdateCoordinator are created and stored in hass.data, so that the
platforms (number, select, switch, sensor, binary_sensor, button, text)
can access them.

Backup and device discovery run exclusively manually via the
corresponding buttons (see button.py), not automatically.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_INTERFACE, CONF_MODEL, DEFAULT_PORT, DEFAULT_TIMEOUT, DOMAIN
from .coordinator import NeumannKHCoordinator
from .ssc_client import SSCClient

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.TEXT,
]


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

