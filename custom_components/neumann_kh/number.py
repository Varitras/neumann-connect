"""Number-Entities: Level, Dimm, Delay und (falls unterstützt) Logo-Helligkeit.

Jede Number-Entity liest ihren aktuellen Wert aus dem Coordinator-Cache und
schreibt bei Änderung direkt per SSC "set" auf den Lautsprecher. Danach wird
ein sofortiger Refresh angestoßen, damit der neue Wert zeitnah in HA sichtbar
ist, statt bis zum nächsten Poll-Zyklus zu warten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONF_MODEL,
    DELAY_MAX,
    DELAY_MIN,
    DIMM_MAX,
    DIMM_MIN,
    DOMAIN,
    LEVEL_MAX,
    LEVEL_MIN,
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_LOGO_BRIGHTNESS,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_LEVEL,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHNumberDescription(NumberEntityDescription):
    """Beschreibung einer Number-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


NUMBER_DESCRIPTIONS: tuple[NeumannKHNumberDescription, ...] = (
    NeumannKHNumberDescription(
        key="output_level",
        translation_key="output_level",
        icon="mdi:volume-high",
        native_min_value=LEVEL_MIN,
        native_max_value=LEVEL_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        ssc_path=PATH_OUTPUT_LEVEL,
    ),
    NeumannKHNumberDescription(
        key="output_dimm",
        translation_key="output_dimm",
        icon="mdi:volume-medium",
        native_min_value=DIMM_MIN,
        native_max_value=DIMM_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        ssc_path=PATH_OUTPUT_DIMM,
    ),
    NeumannKHNumberDescription(
        key="output_delay",
        translation_key="output_delay",
        icon="mdi:timer-outline",
        native_min_value=DELAY_MIN,
        native_max_value=DELAY_MAX,
        native_step=1,
        native_unit_of_measurement="samples",  # 1/48000s pro Sample, siehe khtool --delay
        mode=NumberMode.BOX,
        ssc_path=PATH_OUTPUT_DELAY,
    ),
)

# Nur für KH 80 / KH 150 / KH 120 II verfügbar (nicht KH 750 DSP)
BRIGHTNESS_DESCRIPTION = NeumannKHNumberDescription(
    key="logo_brightness",
    translation_key="logo_brightness",
    icon="mdi:brightness-6",
    native_min_value=BRIGHTNESS_MIN,
    native_max_value=BRIGHTNESS_MAX,
    native_step=1,
    native_unit_of_measurement="%",
    mode=NumberMode.SLIDER,
    ssc_path=PATH_LOGO_BRIGHTNESS,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Number-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(NUMBER_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_LOGO_AND_SAVE:
        descriptions.append(BRIGHTNESS_DESCRIPTION)

    async_add_entities(
        NeumannKHNumber(coordinator, entry, description) for description in descriptions
    )


class NeumannKHNumber(NeumannKHEntity, NumberEntity):
    """Schreibbarer Zahlenwert eines Neumann-KH-Lautsprechers."""

    entity_description: NeumannKHNumberDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Schreibt den neuen Wert per SSC "set" und aktualisiert danach den Cache."""
        # Delay ist ein Integer (Samples), alle anderen Werte sind Fließkomma-dB-Werte.
        payload_value: Any = (
            int(value) if self.entity_description.ssc_path == PATH_OUTPUT_DELAY else float(value)
        )
        await self.coordinator.client.set(self.entity_description.ssc_path, payload_value)
        await self.coordinator.async_request_refresh()
