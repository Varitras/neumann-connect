"""Persistent store (HA store) for name memory, backup and
discovery results. Three separate stores with their own key, thereby
ending up as three separate files under `.storage/`:

- `neumann_kh_names`: last used name per serial number
- `neumann_kh_backups`: settings backup per serial number
- `neumann_kh_discovery`: discovery result per serial number

All three grow without bound (by the user's choice) and survive the
deletion and re-setup of a config entry.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1

# Serializes the read-modify-write sequence of the save functions:
# two parallel saves (e.g. two config flows completing at the same time)
# would otherwise overwrite each other's change (lost update).
_SAVE_LOCK = asyncio.Lock()


def _get_store(hass: HomeAssistant, suffix: str) -> Store:
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}_{suffix}")


# --- Name memory -------------------------------------------------------------


async def async_remember_name(hass: HomeAssistant, serial: str, name: str) -> None:
    """Store the last used name for a serial number."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "names")
        data = await store.async_load() or {"names": {}}
        data.setdefault("names", {})[serial] = name
        await store.async_save(data)


async def async_get_remembered_name(hass: HomeAssistant, serial: str) -> str | None:
    """Return the last used name for a serial number, if known."""
    if not serial:
        return None
    data = await _get_store(hass, "names").async_load() or {"names": {}}
    return data.get("names", {}).get(serial)


# --- Backup ------------------------------------------------------------------


async def async_save_backup(hass: HomeAssistant, serial: str, backup: dict[str, Any]) -> None:
    """Store a settings backup for a serial number."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "backups")
        data = await store.async_load() or {"backups": {}}
        data.setdefault("backups", {})[serial] = backup
        await store.async_save(data)


async def async_get_backup(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Return the last saved backup for a serial number, if present."""
    if not serial:
        return None
    data = await _get_store(hass, "backups").async_load() or {"backups": {}}
    return data.get("backups", {}).get(serial)


# --- Discovery -----------------------------------------------------------


async def async_save_discovery(hass: HomeAssistant, serial: str, discovery: dict[str, Any]) -> None:
    """Store a discovery result (all known values/ranges) for a serial number."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, "discovery")
        data = await store.async_load() or {"discovery": {}}
        data.setdefault("discovery", {})[serial] = discovery
        await store.async_save(data)


async def async_get_discovery(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Return the last saved discovery result for a serial number, if present."""
    if not serial:
        return None
    data = await _get_store(hass, "discovery").async_load() or {"discovery": {}}
    return data.get("discovery", {}).get(serial)
