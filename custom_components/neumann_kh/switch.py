"""Switch-Entities: Mute, Phasenumkehr, Auto-Standby sowie (nur bei erkanntem
Subwoofer) Subwoofer-Phaseninversion und Mute für die Zusatzausgänge out1/out2.

Per echtem Hardware-Test (khtool-Dump einer KH 120 II, Firmware 1_7_3)
korrigiert:
- "solo" existiert im vollständigen Geräte-Dump NICHT und wurde entfernt
  (von diesem Modell/dieser Firmware offenbar nicht unterstützt).
- Es gibt nur EINE Phasenumkehr für den gesamten (Haupt-)Ausgang
  ("audio/out/phaseinversion"), keine getrennte Ein-/Ausgangs-Phasenumkehr
  wie ursprünglich (basierend auf der KH-80-Beispieldoku) angenommen.

Subwoofer-Phaseninversion (ui/subwoofer_phase_inversion) liefert/erwartet
lt. echtem KH-750-Dump die Werte als STRING "0"/"1", nicht als JSON-Bool -
siehe bool_as_string in der Entity-Beschreibung.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_OUT1_MUTE,
    PATH_OUT2_MUTE,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_STANDBY_ENABLED,
    PATH_UI_SUB_PHASE_INVERSION,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSwitchDescription(SwitchEntityDescription):
    """Beschreibung einer Switch-Entity inkl. SSC-Pfad.

    bool_as_string: Manche SSC-Eigenschaften (z. B. subwoofer_phase_inversion)
    liefern/erwarten einen booleschen Zustand als STRING "0"/"1" statt als
    JSON-Bool true/false - siehe echter KH-750-Dump.
    """

    ssc_path: tuple[str, ...] = ()
    bool_as_string: bool = False


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

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES)
SUBWOOFER_SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="subwoofer_phase_inversion",
        translation_key="subwoofer_phase_inversion",
        icon="mdi:sine-wave",
        ssc_path=PATH_UI_SUB_PHASE_INVERSION,
        entity_registry_enabled_default=False,  # unverifiziert, siehe README
        bool_as_string=True,
    ),
    NeumannKHSwitchDescription(
        key="out1_mute",
        translation_key="out1_mute",
        icon="mdi:volume-mute",
        ssc_path=PATH_OUT1_MUTE,
        entity_registry_enabled_default=False,  # nur relevant, falls Out1 belegt ist
    ),
    NeumannKHSwitchDescription(
        key="out2_mute",
        translation_key="out2_mute",
        icon="mdi:volume-mute",
        ssc_path=PATH_OUT2_MUTE,
        entity_registry_enabled_default=False,  # nur relevant, falls Out2 belegt ist
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Switch-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(SWITCH_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.extend(SUBWOOFER_SWITCH_DESCRIPTIONS)

    async_add_entities(
        NeumannKHSwitch(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSwitch(NeumannKHEntity, SwitchEntity):
    """Boolescher SSC-Wert als Switch (ggf. als String "0"/"1" übertragen)."""

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
        if self.entity_description.bool_as_string:
            return str(value) in ("1", "true", "True")
        return bool(value)

    async def _async_set(self, value: bool) -> None:
        """Setzt den Wert; wandelt eine Geräte-Ablehnung in eine klare HA-Fehlermeldung um."""
        payload_value = ("1" if value else "0") if self.entity_description.bool_as_string else value
        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, payload_value)
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
