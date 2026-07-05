"""Dauerhafter Speicher (HA-Store) für Geräte-Discovery-Ergebnisse.

Ein Eintrag pro Seriennummer, wächst unbegrenzt (auf Wunsch des Nutzers).
Überlebt das Löschen und Neueinrichten eines Config Entry. Landet unter
`.storage/neumann_kh_discovery`.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}_discovery"


def _get_store(hass: HomeAssistant) -> Store:
    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


async def async_save_discovery(hass: HomeAssistant, serial: str, discovery: dict[str, Any]) -> None:
    """Speichert ein Discovery-Ergebnis (alle bekannten Werte/Bereiche) für eine Seriennummer."""
    if not serial:
        return
    store = _get_store(hass)
    data = await store.async_load() or {"discovery": {}}
    data.setdefault("discovery", {})[serial] = discovery
    await store.async_save(data)


async def async_get_discovery(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert das zuletzt gespeicherte Discovery-Ergebnis für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _get_store(hass).async_load() or {"discovery": {}}
    return data.get("discovery", {}).get(serial)
