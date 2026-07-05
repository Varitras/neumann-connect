"""Neumann KH (SSC) Integration - Einstiegspunkt.

Pro Config Entry (= ein physischer Lautsprecher) wird ein SSCClient und ein
DataUpdateCoordinator angelegt und in hass.data abgelegt, damit die
Plattformen (number, select, switch, sensor, binary_sensor, button, text)
darauf zugreifen können.

Nach dem ersten erfolgreichen Setup eines noch unbekannten Geräts (per
Seriennummer, siehe storage.py) läuft im Hintergrund einmalig eine
Discovery + ein Backup - damit auch für Geräte, die wir noch nicht kennen,
sofort ein Datenstand vorliegt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from . import storage
from .backup_export import async_build_backup
from .const import CONF_INTERFACE, CONF_MODEL, CONF_SERIAL, DEFAULT_PORT, DEFAULT_TIMEOUT, DOMAIN
from .coordinator import NeumannKHCoordinator
from .discovery_export import async_discover_all_values
from .ssc_client import SSCClient

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

    entry.async_create_background_task(
        hass, _async_first_time_discovery(hass, entry, client), "neumann_kh_first_discovery"
    )
    return True


async def _async_first_time_discovery(
    hass: HomeAssistant, entry: ConfigEntry, client: SSCClient
) -> None:
    """Führt beim allerersten Setup eines Geräts (per Seriennummer) einmalig
    eine Discovery + ein Backup aus. Läuft im Hintergrund, blockiert das
    Setup nicht und darf niemals einen Fehler nach außen werfen.
    """
    serial = entry.data.get(CONF_SERIAL)
    if not serial:
        return
    try:
        if await storage.async_get_discovery(hass, serial) is not None:
            return  # schon einmal gelaufen

        model = entry.data.get(CONF_MODEL)
        timestamp = datetime.now(timezone.utc).isoformat()

        discovery = await async_discover_all_values(client)
        await storage.async_save_discovery(
            hass, serial, {"timestamp": timestamp, "model": model, "serial": serial, **discovery}
        )

        backup_values = await async_build_backup(client, model)
        await storage.async_save_backup(
            hass,
            serial,
            {"timestamp": timestamp, "model": model, "serial": serial, "values": backup_values},
        )
    except Exception:  # noqa: BLE001 - Hintergrund-Task darf das Setup nie stören
        _LOGGER.debug("Automatische Erst-Discovery für %s fehlgeschlagen", serial, exc_info=True)


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
