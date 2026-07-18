"""Sensor entities: measured values (dB) plus pure info/diagnostic sensors.

Info sensors return plain text values and are marked as `entity_category:
diagnostic`. Non-writable values (confirmed by testing) end up here instead
of in number.py/select.py.
"""

from __future__ import annotations

import logging
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
    PATH_INPUT_GAIN,
    PATH_INPUT_SELECT,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_LEVEL,
    PATH_OUT1_LABEL,
    PATH_OUT1_LOUDSPEAKER,
    PATH_OUT2_LABEL,
    PATH_OUT2_LOUDSPEAKER,
    PATH_OUTPUT_LABEL,
    PATH_STANDBY_COUNTDOWN,
    PATH_UI_BASS_MANAGEMENT,
    PATH_UI_CHANNEL_B_INPUT_MODE,
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_OUTPUT_LEVEL,
    PATH_UI_SUB_INPUT_GAIN,
    PATH_UI_SUB_LOW_CUT,
    PATH_UI_SUB_OUTPUT_LEVEL,
    PATH_UI_SUB_PHASE,
    PATH_UI_SUB_PHASE_INVERSION,
    PATH_UI_TREBLE_GAIN,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class NeumannKHSensorDescription(SensorEntityDescription):
    """Description of a sensor entity including the SSC path.

    numeric: Number (float conversion) or plain text.
    kelvin_to_celsius: Raw value is Kelvin, converted to Celsius.
    """

    ssc_path: tuple[str, ...] = ()
    numeric: bool = True
    kelvin_to_celsius: bool = False
    translate_unknown: bool = False  # "UNKNOWN" -> localized "Not assigned"


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

# Only on non-subwoofer models. Confirmed not writable by testing.
NON_SUBWOOFER_SENSOR_DESCRIPTIONS: tuple[NeumannKHSensorDescription, ...] = (
    NeumannKHSensorDescription(
        key="input_gain",
        translation_key="input_gain",
        icon="mdi:tune-vertical",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        ssc_path=PATH_INPUT_GAIN,
    ),
    NeumannKHSensorDescription(
        key="input_select",
        translation_key="input_select",
        icon="mdi:audio-input-rca",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_INPUT_SELECT,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="bass_gain",
        translation_key="bass_gain",
        icon="mdi:sine-wave",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_BASS_GAIN,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="mid_gain",
        translation_key="mid_gain",
        icon="mdi:sine-wave",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_MID_GAIN,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="treble_gain",
        translation_key="treble_gain",
        icon="mdi:sine-wave",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_TREBLE_GAIN,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="output_level_select",
        translation_key="output_level_select",
        icon="mdi:volume-high",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_OUTPUT_LEVEL,
        numeric=False,
    ),
)

# Only on a detected subwoofer (see MODELS_WITH_SUBWOOFER_FEATURES)
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
        entity_registry_enabled_default=False,  # high-frequency live values, off by default
        ssc_path=PATH_METER_OUTPUT_LEVEL,
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
    # Confirmed not writable by testing - read-only values.
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
        key="subwoofer_input_gain",
        translation_key="subwoofer_input_gain",
        icon="mdi:tune-vertical",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        ssc_path=PATH_UI_SUB_INPUT_GAIN,
    ),
    NeumannKHSensorDescription(
        key="subwoofer_low_cut",
        translation_key="subwoofer_low_cut",
        icon="mdi:sine-wave",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        ssc_path=PATH_UI_SUB_LOW_CUT,
    ),
    NeumannKHSensorDescription(
        key="subwoofer_output_level",
        translation_key="subwoofer_output_level",
        icon="mdi:volume-high",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_SUB_OUTPUT_LEVEL,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="subwoofer_phase",
        translation_key="subwoofer_phase",
        icon="mdi:rotate-360",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_SUB_PHASE,
        numeric=False,
    ),
    NeumannKHSensorDescription(
        key="subwoofer_phase_inversion",
        translation_key="subwoofer_phase_inversion",
        icon="mdi:sine-wave",
        entity_category=EntityCategory.DIAGNOSTIC,
        ssc_path=PATH_UI_SUB_PHASE_INVERSION,
        numeric=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the sensor entities for a speaker."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(COMMON_SENSOR_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.extend(SUBWOOFER_SENSOR_DESCRIPTIONS)
    else:
        descriptions.extend(NON_SUBWOOFER_SENSOR_DESCRIPTIONS)

    async_add_entities(
        NeumannKHSensor(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSensor(NeumannKHEntity, SensorEntity):
    """Read-only SSC value as a sensor (numeric, text or temperature)."""

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
                de = (self.hass.config.language or "en").startswith("de")
                return "Nicht zugewiesen" if de else "Not assigned"
            return value

        # Live levels return a LIST (one value per channel) - show the loudest channel.
        if isinstance(value, list):
            numeric_items = [v for v in value if isinstance(v, (int, float))]
            if not numeric_items:
                return None
            value = max(numeric_items)

        # Defensive conversion: non-numeric value -> "unknown" instead of an exception.
        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Non-numeric value for %s: %r - showing 'unknown'",
                self.entity_description.key,
                value,
            )
            return None
        if self.entity_description.kelvin_to_celsius:
            numeric_value -= 273.15
        return numeric_value
