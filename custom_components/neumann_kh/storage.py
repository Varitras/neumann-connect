"""Dauerhafter Speicher (HA-Store) für Gerätedaten, die Config-Entry-Löschungen
überleben sollen: zuletzt verwendeter Name, Backup, Discovery-Export.

Ein Eintrag pro Seriennummer, wächst unbegrenzt (auf Wunsch des Nutzers).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}_devices"


def _get_store(hass: HomeAssistant) -> Store:
    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


async def _async_load(hass: HomeAssistant) -> dict[str, Any]:
    store = _get_store(hass)
    data = await store.async_load()
    return data or {"devices": {}}


async def _async_save(hass: HomeAssistant, data: dict[str, Any]) -> None:
    await _get_store(hass).async_save(data)


async def async_remember_name(hass: HomeAssistant, serial: str, name: str) -> None:
    """Speichert den zuletzt verwendeten Namen für eine Seriennummer."""
    if not serial:
        return
    data = await _async_load(hass)
    devices = data.setdefault("devices", {})
    devices.setdefault(serial, {})["name"] = name
    await _async_save(hass, data)


async def async_get_remembered_name(hass: HomeAssistant, serial: str) -> str | None:
    """Liefert den zuletzt verwendeten Namen für eine Seriennummer, falls bekannt."""
    if not serial:
        return None
    data = await _async_load(hass)
    return data.get("devices", {}).get(serial, {}).get("name")


async def async_save_backup(hass: HomeAssistant, serial: str, backup: dict[str, Any]) -> None:
    """Speichert einen Einstellungs-Backup für eine Seriennummer."""
    if not serial:
        return
    data = await _async_load(hass)
    devices = data.setdefault("devices", {})
    devices.setdefault(serial, {})["backup"] = backup
    await _async_save(hass, data)


async def async_get_backup(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert den zuletzt gespeicherten Backup für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _async_load(hass)
    return data.get("devices", {}).get(serial, {}).get("backup")


async def async_save_discovery(hass: HomeAssistant, serial: str, discovery: dict[str, Any]) -> None:
    """Speichert ein Discovery-Ergebnis (alle bekannten Werte/Bereiche) für eine Seriennummer."""
    if not serial:
        return
    data = await _async_load(hass)
    devices = data.setdefault("devices", {})
    devices.setdefault(serial, {})["discovery"] = discovery
    await _async_save(hass, data)


async def async_get_discovery(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Liefert das zuletzt gespeicherte Discovery-Ergebnis für eine Seriennummer, falls vorhanden."""
    if not serial:
        return None
    data = await _async_load(hass)
    return data.get("devices", {}).get(serial, {}).get("discovery")
