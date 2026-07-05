"""Sensor-Entities: Eingangs-Gain (Trim) und Live-Eingangspegel (Meter).

Beide Werte sind in dB, daher ohne passende HA-`device_class` (es gibt keine
offizielle device_class für Audiopegel in dB) - `state_class` und
`native_unit_of_measurement` werden trotzdem gesetzt, damit Verlauf/Statistik
in HA korrekt funktionieren.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PATH_INPUT_GAIN, PATH_METER_INPUT_LEVEL
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHSensorDescription(SensorEntityDescription):
    """Beschreibung einer Sensor-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


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
        entity_registry_enabled_default=False,  # hochfrequente Live-Werte, standardmäßig aus
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
    """Nur lesbarer SSC-Wert als Sensor."""

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
    def native_value(self) -> float | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        # Die Live-Pegelmessung (m/in/level) liefert lt. echtem Hardware-Test
        # eine LISTE von Werten (ein Wert pro Kanal, z. B. [-122.8, -122.8]),
        # kein Einzelwert. Wir zeigen den lautesten (höchsten) Kanal an, da
        # das für eine Pegelanzeige der praktisch relevante Wert ist.
        if isinstance(value, list):
            if not value:
                return None
            return float(max(value))
        return float(value)
