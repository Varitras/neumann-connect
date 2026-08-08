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


def _get_store(hass: HomeAssistant, kind: str) -> Store:
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}_{kind}")


async def _save_entry(hass: HomeAssistant, kind: str, serial: str, value: Any) -> None:
    """Merge one serial's entry into a store. The store name is also its key."""
    if not serial:
        return
    async with _SAVE_LOCK:
        store = _get_store(hass, kind)
        data = await store.async_load() or {}
        data.setdefault(kind, {})[serial] = value
        await store.async_save(data)


async def _load_entry(hass: HomeAssistant, kind: str, serial: str) -> Any | None:
    """One serial's entry, or None if the store or the serial is unknown."""
    if not serial:
        return None
    data = await _get_store(hass, kind).async_load() or {}
    return data.get(kind, {}).get(serial)


# --- Name memory -------------------------------------------------------------


async def async_remember_name(hass: HomeAssistant, serial: str, name: str) -> None:
    """Store the last used name for a serial number."""
    await _save_entry(hass, "names", serial, name)


async def async_get_remembered_name(hass: HomeAssistant, serial: str) -> str | None:
    """Return the last used name for a serial number, if known."""
    return await _load_entry(hass, "names", serial)


# --- Backup ------------------------------------------------------------------


async def async_save_backup(hass: HomeAssistant, serial: str, backup: dict[str, Any]) -> None:
    """Store a settings backup for a serial number."""
    await _save_entry(hass, "backups", serial, backup)


async def async_get_backup(hass: HomeAssistant, serial: str) -> dict[str, Any] | None:
    """Return the last saved backup for a serial number, if present."""
    return await _load_entry(hass, "backups", serial)


# --- Discovery -----------------------------------------------------------


# Write-only on purpose for now: nothing reads this back - the JSON export
# under <config>/neumann_kh/ is what the user is pointed at. The reader that
# used to sit here was never called and has been removed.
async def async_save_discovery(hass: HomeAssistant, serial: str, discovery: dict[str, Any]) -> None:
    """Store a discovery result (all known values/ranges) for a serial number."""
    await _save_entry(hass, "discovery", serial, discovery)


