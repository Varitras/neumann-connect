"""Shared base class for all Neumann KH entities.

Provides DeviceInfo (manufacturer, model, serial number, firmware) and
`_async_write()`, the one write path of every writable entity: it applies the
value the device confirmed directly instead of waiting for a poll cycle
(otherwise switches and selections spring back).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_MODEL,
    CONF_SERIAL,
    CONF_VENDOR,
    DEFAULT_VENDOR,
    DOMAIN,
    FALLBACK_MODEL,
    PATH_IDENTIFY,
)
from .coordinator import NeumannKHCoordinator
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCLocalModeError, SSCTimeoutError


def unique_id_base(entry: ConfigEntry) -> str:
    """Prefix of every unique ID of this entry's entities."""
    return str(entry.data.get(CONF_SERIAL) or entry.entry_id)


class NeumannKHEntity(CoordinatorEntity[NeumannKHCoordinator]):
    """Base class: provides DeviceInfo and a consistent unique_id base."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        serial = unique_id_base(entry)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=entry.title,
            # Reported by the device; entries created before this was stored,
            # or devices without the field, fall back to Neumann.
            manufacturer=entry.data.get(CONF_VENDOR) or DEFAULT_VENDOR,
            model=entry.data.get(CONF_MODEL, FALLBACK_MODEL),
            sw_version=entry.data.get(CONF_FIRMWARE_VERSION) or None,
        )
        self._unique_id_base = serial

    async def _async_write(
        self, path: tuple[str, ...], value: Any, rejected_key: str = "change_rejected"
    ) -> None:
        """Write one value and publish what the device confirmed.

        The confirmed value goes through coordinator.apply_confirmed_value(),
        which also keeps the slow-poll cache in step - otherwise the next fast
        cycle would merge the old value back in. Without a confirmation the
        path is re-read instead: a missing echo or a line dropped after
        sending does not mean the device kept its old value.
        """
        try:
            confirmed = await self.coordinator.client.set(path, value)
        except SSCLocalModeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="local_mode"
            ) from err
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=rejected_key,
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            self.coordinator.request_reread(path)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        if confirmed is None:
            self.coordinator.request_reread(path)
        else:
            self.coordinator.apply_confirmed_value(path, confirmed)
        # A blinking logo is a momentary action, not a setting to keep.
        if path != PATH_IDENTIFY:
            await self.coordinator.async_persist()
