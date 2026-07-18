"""Text entity: device name (device/name), max. 52 characters, model-independent."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_NAME_MAX_LENGTH, DOMAIN, PATH_DEVICE_NAME
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

DEVICE_NAME_DESCRIPTION = TextEntityDescription(
    key="device_name",
    translation_key="device_name",
    icon="mdi:tag-outline",
    mode=TextMode.TEXT,
    native_max=DEVICE_NAME_MAX_LENGTH,
    entity_registry_enabled_default=False,  # changes the name shown on the device
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the device-name text entity for a speaker."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
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
        return str(value)

    async def async_set_value(self, value: str) -> None:
        try:
            confirmed = await self.coordinator.client.set(PATH_DEVICE_NAME, value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="name_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._apply_confirmed_value(PATH_DEVICE_NAME, confirmed)
