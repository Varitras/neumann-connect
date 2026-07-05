"""Switch-Entities: Mute und Phasenumkehr.

Per echtem Hardware-Test (khtool-Dump einer KH 120 II, Firmware 1_7_3)
korrigiert:
- "solo" existiert im vollständigen Geräte-Dump NICHT und wurde entfernt
  (von diesem Modell/dieser Firmware offenbar nicht unterstützt).
- Es gibt nur EINE Phasenumkehr für den gesamten Ausgang
  ("audio/out/phaseinversion"), keine getrennte Ein-/Ausgangs-Phasenumkehr
  wie ursprünglich (basierend auf der KH-80-Beispieldoku) angenommen.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_STANDBY_ENABLED,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


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
        key="phase_invert",
        translation_key="phase_invert",
        icon="mdi:sine-wave",
        ssc_path=PATH_OUTPUT_PHASE_INVERSION,
        entity_registry_enabled_default=False,
    ),
    NeumannKHSwitchDescription(
        key="auto_standby",
        translation_key="auto_standby",
        icon="mdi:power-sleep",
        ssc_path=PATH_STANDBY_ENABLED,
        entity_registry_enabled_default=False,  # unverifiziertes Feature, siehe README
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

    async def _async_set(self, value: bool) -> None:
        """Setzt den Wert; wandelt eine Geräte-Ablehnung in eine klare HA-Fehlermeldung um."""
        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
