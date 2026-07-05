"""Dauerhafter Speicher (HA-Store) für zuletzt verwendete Gerätenamen.

Ein Eintrag pro Seriennummer, wächst unbegrenzt (auf Wunsch des Nutzers).
Überlebt das Löschen und Neueinrichten eines Config Entry. Landet unter
`.storage/neumann_kh_names`.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}_names"


def _get_store(hass: HomeAssistant) -> Store:
    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


async def async_remember_name(hass: HomeAssistant, serial: str, name: str) -> None:
    """Speichert den zuletzt verwendeten Namen für eine Seriennummer."""
    if not serial:
        return
    store = _get_store(hass)
    data = await store.async_load() or {"names": {}}
    data.setdefault("names", {})[serial] = name
    await store.async_save(data)


async def async_get_remembered_name(hass: HomeAssistant, serial: str) -> str | None:
    """Liefert den zuletzt verwendeten Namen für eine Seriennummer, falls bekannt."""
    if not serial:
        return None
    data = await _get_store(hass).async_load() or {"names": {}}
    return data.get("names", {}).get(serial)
