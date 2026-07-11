"""Gemeinsame Basisklasse für alle Neumann-KH-Entities.

Liefert DeviceInfo (Hersteller, Modell, Seriennummer, Firmware) und
`_apply_confirmed_value()`: übernimmt nach einem "set" den vom Gerät
bestätigten Wert direkt, statt einen kompletten Poll-Zyklus abzuwarten
(vermeidet Race Condition beim Zurückspringen von Schaltern/Auswahlen).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FIRMWARE_VERSION, CONF_MODEL, CONF_SERIAL, DOMAIN
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
            sw_version=entry.data.get(CONF_FIRMWARE_VERSION) or None,
        )
        self._unique_id_base = serial

    async def _apply_confirmed_value(self, path: tuple[str, ...], confirmed_value: Any) -> None:
        """Übernimmt einen vom Gerät bestätigten Wert direkt, ohne neue Netzwerk-Anfrage.

        Delegiert an coordinator.apply_confirmed_value(), das neben den
        Coordinator-Daten auch den Slow-Poll-Cache pflegt (sonst würde der
        nächste schnelle Zyklus den Wert wieder überschreiben). Liefert das
        Gerät keinen eindeutigen Wert (None), wird stattdessen ein normaler
        Refresh angestoßen.
        """
        if confirmed_value is None:
            await self.coordinator.async_request_refresh()
            return
        self.coordinator.apply_confirmed_value(path, confirmed_value)
