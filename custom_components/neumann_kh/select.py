"""Select-Entity: Subwoofer-Ausgangspegel (feste SPL-Stufen).

`ui/subwoofer_output_level` liefert lt. echtem KH-750-Dump einen STRING-ENUM
("94"), keinen kontinuierlichen Zahlenwert - passend zu den bei anderen
KH-Modellen dokumentierten festen SPL-Stufen (z. B. KH 120A: Ausgangspegel
94/100/108/114 dB SPL bei 0 dBu Eingang, über einen physischen Rückseiten-
Schalter gewählt). Da es sich um eine feste Auswahl fester Stufen handelt
(kein Schieberegler-Wertebereich), ist die HA-Domain `select` die passende
Wahl, nicht `number`.

Nur bei erkanntem Subwoofer angelegt (siehe MODELS_WITH_SUBWOOFER_FEATURES).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_UI_SUB_OUTPUT_LEVEL,
    SUB_OUTPUT_LEVEL_OPTIONS,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSelectDescription(SelectEntityDescription):
    """Beschreibung einer Select-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


SUBWOOFER_OUTPUT_LEVEL_DESCRIPTION = NeumannKHSelectDescription(
    key="subwoofer_output_level",
    translation_key="subwoofer_output_level",
    icon="mdi:volume-high",
    options=list(SUB_OUTPUT_LEVEL_OPTIONS),
    entity_registry_enabled_default=False,  # Optionen unverifiziert, siehe README
    ssc_path=PATH_UI_SUB_OUTPUT_LEVEL,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Select-Entity nur bei erkanntem Subwoofer an."""
    if entry.data.get(CONF_MODEL) not in MODELS_WITH_SUBWOOFER_FEATURES:
        return

    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NeumannKHSelect(coordinator, entry, SUBWOOFER_OUTPUT_LEVEL_DESCRIPTION)])


class NeumannKHSelect(NeumannKHEntity, SelectEntity):
    """Feste Auswahl (String-Enum) eines Neumann-KH-Subwoofers."""

    entity_description: NeumannKHSelectDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return str(value)

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, option)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Auswahl abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self.coordinator.async_request_refresh()
