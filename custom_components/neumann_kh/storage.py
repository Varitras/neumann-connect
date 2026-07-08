"""Dauerhafter Speicher (HA-Store) für Namensgedächtnis, Backup und
Discovery-Ergebnisse. Drei getrennte Speicher mit eigenem Schlüssel, landen
dadurch auch als drei separate Dateien unter `.storage/`:

- `neumann_kh_names`: zuletzt verwendeter Name je Seriennummer
- `neumann_kh_backups`: Einstellungs-Backup je Seriennummer
- `neumann_kh_discovery`: Discovery-Ergebnis je Seriennummer

Alle drei wachsen unbegrenzt (auf Wunsch des Nutzers) und überleben das
Löschen und Neueinrichten eines Config Entry.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1

# Serialisiert die Lesen-Ändern-Schreiben-Sequenz der Save-Funktionen:
# zwei parallele Saves (z. B. zwei gleichzeitig abgeschlossene Config Flows)
# würden sich sonst gegenseitig die Änderung überschreiben (Lost Update).
_SAVE_LOCK = asyncio.Lock()


def _get_store(hass: HomeAssistant, suffix: str) -> Store:
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}_{suffix}")


# --- Namensgedächtnis --------------------------------------------------------


async def async_remember_name(hass: HomeAssistant, serial: str, name: str) -> None:
    """Speichert den zuletzt verwendeten Namen für eine Seriennummer."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "names")
        data = await store.async_load() or {"names": {}}
        data.setdefault("names", {})[serial] = name
        await store.async_save(data)


async def async_get_remembered_name(hass: HomeAssistant, serial: str) -> str | None:
    """Liefert den zuletzt verwendeten Namen für eine Seriennummer, falls bekannt."""
    if not serial:
        return None
    data = await _get_store(hass, "names").async_load() or {"names": {}}
    return data.get("names", {}).get(serial)


# --- Backup ------------------------------------------------------------------


async def async_save_backup(hass: HomeAssistant, serial: str, backup: dict[str, Any]) -> None:
    """Speichert einen Einstellungs-Backup für eine Seriennummer."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "backups")
        data = await store.async_load() or {"backups": {}}
        data.setdefault("backups", {})[serial] = backup
        await store.async_save(data)


async def async_get_backup(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert den zuletzt gespeicherten Backup für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _get_store(hass, "backups").async_load() or {"backups": {}}
    return data.get("backups", {}).get(serial)


# --- Discovery -----------------------------------------------------------


async def async_save_discovery(hass: HomeAssistant, serial: str, discovery: dict[str, Any]) -> None:
    """Speichert ein Discovery-Ergebnis (alle bekannten Werte/Bereiche) für eine Seriennummer."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "discovery")
        data = await store.async_load() or {"discovery": {}}
        data.setdefault("discovery", {})[serial] = discovery
        await store.async_save(data)


async def async_get_discovery(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert das zuletzt gespeicherte Discovery-Ergebnis für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _get_store(hass, "discovery").async_load() or {"discovery": {}}
    return data.get("discovery", {}).get(serial)
