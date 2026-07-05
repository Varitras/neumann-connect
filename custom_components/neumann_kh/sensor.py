"""Sensor-Entities: Messwerte (dB) sowie reine Info-/Diagnose-Sensoren.

Messwerte (Eingangsverstärkung, Live-Pegel, Standby-Countdown, Temperatur)
sind ohne passende HA-`device_class` fuer dB-Werte (es gibt keine offizielle
device_class für Audiopegel in dB) - `state_class` und
`native_unit_of_measurement` werden trotzdem gesetzt, damit Verlauf/Statistik
in HA korrekt funktionieren. Die Temperatur NUTZT die offizielle
`SensorDeviceClass.TEMPERATURE`.

Info-Sensoren (Gerätename, Hardware-Version, Eingangstyp, Steuerungsmodus,
Bass-Management, Kanalzuordnung) liefern reine Textwerte ohne
Einheit/state_class und sind als `entity_category: diagnostic` markiert.

Subwoofer-spezifische Sensoren (Temperatur, Ausgangspegel-Meter, Bass-
Management-Infos, out1/out2-Label/Lautsprecher) werden NUR bei erkanntem
Subwoofer angelegt (siehe MODELS_WITH_SUBWOOFER_FEATURES) - per echtem
KH-750-Dump (Firmware 2_1_2) verifiziert.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_DEVICE_NAME,
    PATH_DEVICE_TEMPERATURE,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_GAIN,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_LEVEL,
    PATH_OUT1_LABEL,
    PATH_OUT1_LOUDSPEAKER,
    PATH_OUT2_LABEL,
    PATH_OUT2_LOUDSPEAKER,
    PATH_STANDBY_COUNTDOWN,
    PATH_UI_BASS_MANAGEMENT,
    PATH_UI_CHANNEL_B_INPUT_MODE,
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
    kelvin_to_celsius: Rohwert wird als Kelvin interpretiert und nach Celsius
    umgerechnet (siehe PATH_DEVICE_TEMPERATURE-Kommentar in const.py -
    ANNAHME, nicht offiziell verifiziert).
    """

    ssc_path: tuple[str, ...] = ()
    numeric: bool = True
    kelvin_to_celsius: bool = False


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

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES)
SUBWOOFER_SENSOR_DESCRIPTIONS: tuple[NeumannKHSensorDescription, ...] = (
    NeumannKHSensorDescription(
        key="device_temperature",
        translation_key="device_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,  # Einheiten-Annahme (Kelvin) unverifiziert, siehe README
        ssc_path=PATH_DEVICE_TEMPERATURE,
        kelvin_to_celsius=True,
    ),
    NeumannKHSensorDescription(
        key="output_level_meter",
        translation_key="output_level_meter",
        icon="mdi:gauge",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,  # hochfrequente Live-Werte, standardmäßig aus
        ssc_path=PATH_METER_OUTPUT_LEVEL,
    ),
    NeumannKHSensorDescription(
        key="bass_management",
        translation_key="bass_management",
        icon="mdi:speaker",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_BASS_MANAGEMENT,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="channel_b_input_mode",
        translation_key="channel_b_input_mode",
        icon="mdi:import",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_CHANNEL_B_INPUT_MODE,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="out1_label",
        translation_key="out1_label",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT1_LABEL,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="out1_loudspeaker",
        translation_key="out1_loudspeaker",
        icon="mdi:speaker",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT1_LOUDSPEAKER,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="out2_label",
        translation_key="out2_label",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT2_LABEL,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="out2_loudspeaker",
        translation_key="out2_loudspeaker",
        icon="mdi:speaker",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT2_LOUDSPEAKER,
        numeric=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Sensor-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(SENSOR_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.extend(SUBWOOFER_SENSOR_DESCRIPTIONS)

    async_add_entities(
        NeumannKHSensor(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSensor(NeumannKHEntity, SensorEntity):
    """Nur lesbarer SSC-Wert als Sensor (numerisch, Text oder Temperatur)."""

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

        # Die Live-Pegelmessungen (m/in/level, m/out/level) liefern lt.
        # echtem Hardware-Test LISTEN von Werten (ein Wert pro Kanal), kein
        # Einzelwert. Wir zeigen den lautesten (höchsten) Kanal an, da das
        # für eine Pegelanzeige der praktisch relevante Wert ist.
        if isinstance(value, list):
            if not value:
                return None
            value = max(value)

        numeric_value = float(value)
        if self.entity_description.kelvin_to_celsius:
            numeric_value -= 273.15
        return numeric_value
