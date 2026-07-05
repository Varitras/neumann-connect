"""Neumann KH (SSC) Integration - Einstiegspunkt.

Pro Config Entry (= ein physischer Lautsprecher) wird ein SSCClient und ein
DataUpdateCoordinator angelegt und in hass.data abgelegt, damit die
Plattformen (number, select, switch, sensor, binary_sensor, button) darauf
zugreifen können.
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
    """Richtet einen Config Entry (einen Lautsprecher) ein."""
    client = SSCClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        interface=entry.data.get(CONF_INTERFACE) or None,
        timeout=DEFAULT_TIMEOUT,
    )

    coordinator = NeumannKHCoordinator(
        hass, client, entry.title, model=entry.data.get(CONF_MODEL)
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlädt einen Config Entry und schließt die TCP-Verbindung sauber."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator: NeumannKHCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        # Verbindung immer schließen, unabhängig vom Plattform-Unload-Ergebnis.
        await coordinator.client.close()
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Lädt den Entry neu, falls Optionen geändert werden."""
    await hass.config_entries.async_reload(entry.entry_id)
