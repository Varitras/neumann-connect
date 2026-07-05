"""Binary-Sensor-Entities: Clip-Anzeige, Warnungs-Indikator sowie (nur
Subwoofer) Digital-Bypass und Auto-Standby-Status (nur lesend).

Clip/Warnungen liefert das Gerät als Liste (ein Wert pro Kanal).

Auto-Standby ist modellspezifisch: auf der KH 120 II als Switch schreibbar
(siehe switch.py), auf der KH 750 nur lesend (Schreiben abgelehnt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_DIGITAL_BYPASS,
    PATH_METER_CLIP,
    PATH_METER_OUTPUT_CLIP,
    PATH_STANDBY_ENABLED,
    PATH_WARNINGS,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity

# Wert im warnungsfreien Normalzustand.
_NO_WARNING = "NO_WARNING"


@dataclass(frozen=True, kw_only=True)
class NeumannKHBinarySensorDescription(BinarySensorEntityDescription):
    """Beschreibung einer Binary-Sensor-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()
    is_warnings: bool = False


BINARY_SENSOR_DESCRIPTIONS: tuple[NeumannKHBinarySensorDescription, ...] = (
    NeumannKHBinarySensorDescription(
        key="input_clip",
        translation_key="input_clip",
        icon="mdi:alert-decagram-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        ssc_path=PATH_METER_CLIP,
    ),
    NeumannKHBinarySensorDescription(
        key="warning",
        translation_key="warning",
        icon="mdi:alert-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_WARNINGS,
        is_warnings=True,
    ),
)

# Nur bei erkanntem Subwoofer.
SUBWOOFER_BINARY_SENSOR_DESCRIPTIONS: tuple[NeumannKHBinarySensorDescription, ...] = (
    NeumannKHBinarySensorDescription(
        key="output_clip",
        translation_key="output_clip",
        icon="mdi:alert-decagram-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_registry_enabled_default=False,
        ssc_path=PATH_METER_OUTPUT_CLIP,
    ),
    NeumannKHBinarySensorDescription(
        key="digital_bypass",
        translation_key="digital_bypass",
        icon="mdi:transit-connection-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_DIGITAL_BYPASS,
    ),
    NeumannKHBinarySensorDescription(
        key="auto_standby",
        translation_key="auto_standby",
        icon="mdi:power-sleep",
        ssc_path=PATH_STANDBY_ENABLED,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Binary-Sensor-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(BINARY_SENSOR_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.extend(SUBWOOFER_BINARY_SENSOR_DESCRIPTIONS)

    async_add_entities(
        NeumannKHBinarySensor(coordinator, entry, description) for description in descriptions
    )


class NeumannKHBinarySensor(NeumannKHEntity, BinarySensorEntity):
    """Boolescher Zustand, abgeleitet aus einer Listen-Antwort des Geräts."""

    entity_description: NeumannKHBinarySensorDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        if self.entity_description.is_warnings:
            # "Problem" = irgendeine Warnung außer dem Normalzustand NO_WARNING.
            if isinstance(value, list):
                return any(item != _NO_WARNING for item in value)
            return value != _NO_WARNING
        # Clip (Eingang oder Ausgang): "Problem" = mindestens ein Kanal clippt gerade.
        if isinstance(value, list):
            return any(bool(item) for item in value)
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return {"raw_value": value}
