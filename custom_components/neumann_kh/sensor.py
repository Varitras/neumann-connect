"""Sensor-Entities: Messwerte (dB) sowie reine Info-/Diagnose-Sensoren.

Messwerte (Live-Pegel, Standby-Countdown, Temperatur) sind ohne passende
HA-`device_class` für dB-Werte (es gibt keine offizielle device_class für
Audiopegel in dB) - `state_class` und `native_unit_of_measurement` werden
trotzdem gesetzt. Die Temperatur NUTZT die offizielle
`SensorDeviceClass.TEMPERATURE`.

Info-Sensoren liefern reine Textwerte ohne Einheit/state_class und sind als
`entity_category: diagnostic` markiert.

WICHTIG: `ui/input_gain` und `ui/control_mode` sind laut khtool-Metadaten
SCHREIBBAR und deshalb NICHT hier, sondern als `number` bzw. `select`
umgesetzt (siehe number.py/select.py) - ein Pfad bekommt nur EINE Entity,
nie eine read-only UND eine read-write Variante gleichzeitig.
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
    PATH_DEVICE_TEMPERATURE,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_LEVEL,
    PATH_OUT1_LABEL,
    PATH_OUT1_LOUDSPEAKER,
    PATH_OUT2_LABEL,
    PATH_OUT2_LOUDSPEAKER,
    PATH_OUTPUT_LABEL,
    PATH_STANDBY_COUNTDOWN,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHSensorDescription(SensorEntityDescription):
    """Beschreibung einer Sensor-Entity inkl. SSC-Pfad.

    numeric: Ob der Wert als Zahl behandelt werden soll (float-Konvertierung,
    z. B. für dB-Messwerte) oder als reiner Text (z. B. Eingangstyp).
    kelvin_to_celsius: Rohwert wird als Kelvin interpretiert und nach Celsius
    umgerechnet (laut khtool-Metadaten bestätigt: Einheit "K").
    """

    ssc_path: tuple[str, ...] = ()
    numeric: bool = True
    kelvin_to_celsius: bool = False
    translate_unknown: bool = False  # "UNKNOWN" -> "Nicht zugewiesen" (siehe Sammel-Liste Punkt 9)


COMMON_SENSOR_DESCRIPTIONS: tuple[NeumannKHSensorDescription, ...] = (
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
        entity_registry_enabled_default=False,
        ssc_path=PATH_STANDBY_COUNTDOWN,
    ),
    NeumannKHSensorDescription(
        key="hw_version",
        translation_key="hw_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_IDENTITY_HW_VERSION,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="input_current",
        translation_key="input_current",
        icon="mdi:audio-input-rca",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_INPUT_CURRENT,
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
    # out1/out2 "loudspeaker" hat laut khtool-Metadaten zwar eine feste
    # Optionsliste, aber KEIN "writeable"-Flag (anders als alle anderen
    # bestätigt schreibbaren Felder) - bleibt deshalb vorsichtshalber
    # read-only, statt es ungeprüft als `select` umzusetzen.
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
        translate_unknown=True,
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
        translate_unknown=True,
    ),
    NeumannKHSensorDescription(
        key="output_label",
        translation_key="output_label",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_OUTPUT_LABEL,
        numeric=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Sensor-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(COMMON_SENSOR_DESCRIPTIONS)
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
            if self.entity_description.translate_unknown and value == "UNKNOWN":
                return "Nicht zugewiesen"
            return value

        # Die Live-Pegelmessungen (m/in/level, m/out/level) liefern lt.
        # echtem Hardware-Test LISTEN von Werten (ein Wert pro Kanal), kein
        # Einzelwert. Wir zeigen den lautesten (höchsten) Kanal an.
        if isinstance(value, list):
            if not value:
                return None
            value = max(value)

        numeric_value = float(value)
        if self.entity_description.kelvin_to_celsius:
            numeric_value -= 273.15
        return numeric_value
