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
)
from .coordinator import NeumannKHCoordinator
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError


class NeumannKHEntity(CoordinatorEntity[NeumannKHCoordinator]):
    """Base class: provides DeviceInfo and a consistent unique_id base."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        serial = entry.data.get(CONF_SERIAL) or entry.entry_id
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
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=rejected_key,
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            await self.coordinator.async_request_reread(path)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        if confirmed is None:
            await self.coordinator.async_request_reread(path)
            return
        self.coordinator.apply_confirmed_value(path, confirmed)
