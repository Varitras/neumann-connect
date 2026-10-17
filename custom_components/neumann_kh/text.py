"""Text entity: device name (device/name), max. 52 characters, model-independent."""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_NAME_MAX_LENGTH, PATH_DEVICE_NAME
from .coordinator import NeumannKHConfigEntry, NeumannKHCoordinator
from .entity import NeumannKHEntity

_LOGGER = logging.getLogger(__name__)

DEVICE_NAME_DESCRIPTION = TextEntityDescription(
    key="device_name",
    translation_key="device_name",
    icon="mdi:tag-outline",
    mode=TextMode.TEXT,
    native_max=DEVICE_NAME_MAX_LENGTH,
    entity_registry_enabled_default=False,  # changes the name shown on the device
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NeumannKHConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the device-name text entity for a speaker."""
    coordinator = entry.runtime_data
    async_add_entities([NeumannKHDeviceNameText(coordinator, entry)])


class NeumannKHDeviceNameText(NeumannKHEntity, TextEntity):
    """Writable device name of the speaker."""

    entity_description = DEVICE_NAME_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_device_name"

    @property
    def native_value(self) -> str | None:
        value = self.coordinator.value(PATH_DEVICE_NAME)
        if value is None:
            return None
        name = str(value)
        # Home Assistant refuses a text state longer than native_max: the
        # entity would never be added, and with it the way to shorten the name.
        if len(name) > DEVICE_NAME_MAX_LENGTH:
            _LOGGER.debug(
                "Device name longer than %d characters - showing 'unknown'", DEVICE_NAME_MAX_LENGTH
            )
            return None
        return name

    async def async_set_value(self, value: str) -> None:
        await self._async_write(PATH_DEVICE_NAME, value, rejected_key="name_rejected")
