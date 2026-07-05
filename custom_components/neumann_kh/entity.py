"""Gemeinsame Basisklasse für alle Neumann-KH-Entities.

Bündelt die DeviceInfo (Hersteller, Modell, Seriennummer), damit alle
Entities eines Lautsprechers im HA-Geräteregister korrekt einem einzigen
Gerät zugeordnet werden.

Bündelt außerdem `_apply_confirmed_value()`: Nach einem "set" bestätigt das
Gerät in DERSELBEN Antwort bereits den neuen, übernommenen Wert. Vorher
wurde diese Bestätigung verworfen und stattdessen ein kompletter (langsamer,
~20+ Einzelabfragen) Poll-Zyklus angestoßen - das führte zu einer Race
Condition: Wurde der geänderte Wert dabei abgefragt, BEVOR das Gerät ihn
intern vollständig übernommen hatte, kam der alte Wert zurück und der
Schalter/die Auswahl sprang kurzzeitig zurück, bis der nächste reguläre
Poll-Zyklus (bis zu 30s später) den echten Wert lieferte. Die bestätigte
Antwort direkt zu übernehmen vermeidet dieses Wettrennen komplett.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._util import build_nested, deep_merge
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
        """Übernimmt einen vom Gerät bestätigten Wert sofort in den Cache.

        Schreibt den Wert direkt in `coordinator.data` (ohne erneute
        Netzwerk-Anfrage) und aktualisiert den Zustand dieser Entity sofort.
        Andere Entities desselben Geräts sehen den neuen Wert beim nächsten
        regulären Poll-Zyklus (max. 30s) - unkritisch, da nur die gerade
        geänderte Entity eine sofortige Rückmeldung braucht.

        Falls das Gerät keinen eindeutigen Wert zurückliefert (None),
        stattdessen sicherheitshalber einen echten Refresh anstoßen, damit
        der Zustand langfristig nicht falsch hängen bleibt.
        """
        if confirmed_value is None:
            await self.coordinator.async_request_refresh()
            return

        if self.coordinator.data is None:
            self.coordinator.data = {}
        deep_merge(self.coordinator.data, build_nested(path, confirmed_value))
        self.async_write_ha_state()
