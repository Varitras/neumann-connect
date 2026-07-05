"""Sensor-Entities: Messwerte (dB) sowie reine Info-/Diagnose-Sensoren.

Messwerte (Eingangsverstärkung, Live-Pegel, Standby-Countdown) sind ohne
passende HA-`device_class` (es gibt keine offizielle device_class für
Audiopegel in dB) - `state_class` und `native_unit_of_measurement` werden
trotzdem gesetzt, damit Verlauf/Statistik in HA korrekt funktionieren.

Info-Sensoren (Gerätename, Hardware-Version, Eingangstyp, Steuerungsmodus)
liefern reine Textwerte ohne Einheit/state_class und sind als
`entity_category: diagnostic` markiert, damit sie nicht die normale
Geräteübersicht überladen, sondern unter "Diagnose" einsortiert werden.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    PATH_DEVICE_NAME,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_GAIN,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_METER_INPUT_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    PATH_UI_CONTROL_MODE,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHSensorDescription(SensorEntityDescription):
    """Beschreibung einer Sensor-Entity inkl. SSC-Pfad.

    numeric: Ob der Wert als Zahl behandelt werden soll (float-Konvertierung,
    z. B. für dB-Messwerte) oder als reiner Text (z. B. Gerätename,
    Eingangstyp). Default True.
    """

    ssc_path: tuple[str, ...] = ()
    numeric: bool = True


SENSOR_DESCRIPTIONS: tuple[NeumannKHSensorDescription, ...] = (
    NeumannKHSensorDescription(
        key="input_gain",
        translation_key="input_gain",
        icon="mdi:tune-vertical",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        ssc_path=PATH_INPUT_GAIN,
    ),
    NeumannKHSensorDescription(
        key="input_level_meter",
        translation_key="input_level_meter",
        icon="mdi:gauge",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        ssc_path=PATH_METER_INPUT_LEVEL,
    ),
    NeumannKHSensorDescription(
        key="standby_countdown",
        translation_key="standby_countdown",
        icon="mdi:timer-sand",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,  # gehört zum unverifizierten Auto-Standby-Feature
        ssc_path=PATH_STANDBY_COUNTDOWN,
    ),
    NeumannKHSensorDescription(
        key="device_name",
        translation_key="device_name",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_DEVICE_NAME,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="hw_version",
        translation_key="hw_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_IDENTITY_HW_VERSION,
        numeric=False,  # Rohwert unverändert anzeigen, keine float-Konvertierung nötig
    ),
    NeumannKHSensorDescription(
        key="input_current",
        translation_key="input_current",
        icon="mdi:audio-input-rca",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_INPUT_CURRENT,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="input_interface_type",
        translation_key="input_interface_type",
        icon="mdi:audio-input-stereo-minijack",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_INPUT_INTERFACE_TYPE,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="control_mode",
        translation_key="control_mode",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_CONTROL_MODE,
        numeric=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Sensor-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NeumannKHSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class NeumannKHSensor(NeumannKHEntity, SensorEntity):
    """Nur lesbarer SSC-Wert als Sensor (numerisch oder Text)."""

    entity_description: NeumannKHSensorDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def native_value(self):
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        if not self.entity_description.numeric:
            return value
        # Die Live-Pegelmessung (m/in/level) liefert lt. echtem Hardware-Test
        # eine LISTE von Werten (ein Wert pro Kanal, z. B. [-122.8, -122.8]),
        # kein Einzelwert. Wir zeigen den lautesten (höchsten) Kanal an, da
        # das für eine Pegelanzeige der praktisch relevante Wert ist.
        if isinstance(value, list):
            if not value:
                return None
            return float(max(value))
        return float(value)
