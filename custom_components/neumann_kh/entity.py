"""Gemeinsame Basisklasse für alle Neumann-KH-Entities.

Bündelt die DeviceInfo (Hersteller, Modell, Seriennummer), damit alle
Entities eines Lautsprechers im HA-Geräteregister korrekt einem einzigen
Gerät zugeordnet werden.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, CONF_SERIAL, DOMAIN
from .coordinator import NeumannKHCoordinator


class NeumannKHEntity(CoordinatorEntity[NeumannKHCoordinator]):
    """Basisklasse: liefert DeviceInfo und eine konsistente unique_id-Basis."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        serial = entry.data.get(CONF_SERIAL) or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=entry.title,
            manufacturer="Georg Neumann GmbH",
            model=entry.data.get(CONF_MODEL, "KH DSP"),
        )
        self._unique_id_base = serial
