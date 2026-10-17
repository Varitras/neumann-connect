"""Select entities: fixed value choices (string enums)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import INPUT_INTERFACE_OPTIONS, PATH_INPUT_INTERFACE_TYPE
from .coordinator import NeumannKHConfigEntry, NeumannKHCoordinator
from .entity import NeumannKHEntity


@dataclass(frozen=True, kw_only=True)
class NeumannKHSelectDescription(SelectEntityDescription):
    """Description of a select entity including the SSC path."""

    ssc_path: tuple[str, ...] = ()


# Confirmed writable on the KH 120 II and the KH 750 DSP, so it is the same on
# every model and enabled by default. This used to be a builder taking
# is_subwoofer "in case a differentiation becomes necessary later" - it never
# was, and the argument only made the call sites look model-dependent.
INPUT_INTERFACE_DESCRIPTION = NeumannKHSelectDescription(
    key="input_interface",
    translation_key="input_interface",
    icon="mdi:audio-input-stereo-minijack",
    options=list(INPUT_INTERFACE_OPTIONS),
    entity_registry_enabled_default=True,
    ssc_path=PATH_INPUT_INTERFACE_TYPE,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NeumannKHConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the select entities for a speaker."""
    coordinator = entry.runtime_data

    async_add_entities([NeumannKHSelect(coordinator, entry, INPUT_INTERFACE_DESCRIPTION)])


class NeumannKHSelect(NeumannKHEntity, SelectEntity):
    """Fixed choice (string enum) of a Neumann KH speaker."""

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
        await self._async_write(
            self.entity_description.ssc_path, option, rejected_key="selection_rejected"
        )
