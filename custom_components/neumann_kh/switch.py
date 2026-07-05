"""Switch-Entities: Mute, Solo, Eingangs-Phasenumkehr, Ausgangs-Phasenkorrektur."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    PATH_INPUT_PHASE_INVERT,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_CORRECTION,
    PATH_OUTPUT_SOLO,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHSwitchDescription(SwitchEntityDescription):
    """Beschreibung einer Switch-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="mute",
        translation_key="mute",
        icon="mdi:volume-mute",
        ssc_path=PATH_OUTPUT_MUTE,
    ),
    NeumannKHSwitchDescription(
        key="solo",
        translation_key="solo",
        icon="mdi:speaker-wireless",
        ssc_path=PATH_OUTPUT_SOLO,
        entity_registry_enabled_default=False,
    ),
    NeumannKHSwitchDescription(
        key="input_phase_invert",
        translation_key="input_phase_invert",
        icon="mdi:sine-wave",
        ssc_path=PATH_INPUT_PHASE_INVERT,
        entity_registry_enabled_default=False,
    ),
    NeumannKHSwitchDescription(
        key="output_phase_correction",
        translation_key="output_phase_correction",
        icon="mdi:waveform",
        ssc_path=PATH_OUTPUT_PHASE_CORRECTION,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Switch-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NeumannKHSwitch(coordinator, entry, description)
        for description in SWITCH_DESCRIPTIONS
    )


class NeumannKHSwitch(NeumannKHEntity, SwitchEntity):
    """Boolescher SSC-Wert als Switch."""

    entity_description: NeumannKHSwitchDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set(self.entity_description.ssc_path, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set(self.entity_description.ssc_path, False)
        await self.coordinator.async_request_refresh()
