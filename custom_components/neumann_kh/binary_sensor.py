"""Binary-Sensor-Entities: Clip-Anzeige und Warnungs-Indikator.

Beide Werte liefert das Gerät als LISTE (Clip: ein Bool pro Kanal;
Warnungen: eine Liste von Warncodes, z. B. ["NO_WARNING"] im Normalzustand).
Die jeweils rohe Liste wird zusätzlich als Attribut mitgegeben, damit man bei
Bedarf nachschauen kann, welcher Kanal/welche genaue Warnung betroffen ist.
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

# Wert, den das Gerät im warnungsfreien Normalzustand liefert (siehe echter
# khtool-Dump: {"warnings":["NO_WARNING"]}).
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
        entity_category="diagnostic",
        ssc_path=PATH_WARNINGS,
        is_warnings=True,
    ),
    NeumannKHBinarySensorDescription(
        key="auto_standby",
        translation_key="auto_standby",
        icon="mdi:power-sleep",
        entity_registry_enabled_default=False,
        ssc_path=PATH_STANDBY_ENABLED,
    ),
)

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES) -
# Pendant zu input_clip, aber für die Ausgänge (Hauptausgang + out1 + out2).
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
        entity_category="diagnostic",
        ssc_path=PATH_DIGITAL_BYPASS,
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
