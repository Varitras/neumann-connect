"""Select entities: fixed value choices (string enums).

"Control mode" (NETWORK/LOCAL) always stays disabled: switching to LOCAL cuts
off network control until it is manually reset on the device.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONTROL_MODE_OPTIONS,
    DOMAIN,
    INPUT_INTERFACE_OPTIONS,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_UI_CONTROL_MODE,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSelectDescription(SelectEntityDescription):
    """Description of a select entity including the SSC path."""

    ssc_path: tuple[str, ...] = ()


# Always created, deliberately always disabled (safety exception).
CONTROL_MODE_DESCRIPTION = NeumannKHSelectDescription(
    key="control_mode",
    translation_key="control_mode",
    icon="mdi:network-outline",
    options=list(CONTROL_MODE_OPTIONS),
    entity_registry_enabled_default=False,
    ssc_path=PATH_UI_CONTROL_MODE,
)


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
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the select entities for a speaker."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        CONTROL_MODE_DESCRIPTION,
        INPUT_INTERFACE_DESCRIPTION,
    ]

    async_add_entities(
        NeumannKHSelect(coordinator, entry, description) for description in descriptions
    )


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
        try:
            confirmed = await self.coordinator.client.set(self.entity_description.ssc_path, option)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="selection_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._apply_confirmed_value(self.entity_description.ssc_path, confirmed)
