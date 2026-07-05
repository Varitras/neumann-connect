"""Dauerhafter Speicher (HA-Store) für Einstellungs-Backups.

Ein Eintrag pro Seriennummer, wächst unbegrenzt (auf Wunsch des Nutzers).
Überlebt das Löschen und Neueinrichten eines Config Entry. Landet unter
`.storage/neumann_kh_backups`.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}_backups"


def _get_store(hass: HomeAssistant) -> Store:
    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


async def async_save_backup(hass: HomeAssistant, serial: str, backup: dict[str, Any]) -> None:
    """Speichert einen Einstellungs-Backup für eine Seriennummer."""
    if not serial:
        return
    store = _get_store(hass)
    data = await store.async_load() or {"backups": {}}
    data.setdefault("backups", {})[serial] = backup
    await store.async_save(data)


async def async_get_backup(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert den zuletzt gespeicherten Backup für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _get_store(hass).async_load() or {"backups": {}}
    return data.get("backups", {}).get(serial)
