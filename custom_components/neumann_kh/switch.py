"""Switch-Entities: Mute, Gerät identifizieren, Auto-Standby (nur Nicht-
Subwoofer), Phasenumkehr (nur Nicht-Subwoofer).

"Identifizieren" ist ein Schalter statt eines Auto-Stopp-Buttons, da das
Blinken erst nach mehreren Minuten von selbst aufhört.

"Auto-Standby" ist modellspezifisch schreibbar: auf der KH 120 II
funktioniert das Schreiben, auf der KH 750 nicht (siehe binary_sensor.py).
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
    PATH_IDENTIFY,
    PATH_OUT1_MUTE,
    PATH_OUT2_MUTE,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_STANDBY_ENABLED,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .eq import NeumannKHEQBandSwitch, build_eq_switch_descriptions
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSwitchDescription(SwitchEntityDescription):
    """Beschreibung einer Switch-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


# Immer angelegt (modellunabhängig)
COMMON_SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="mute",
        translation_key="mute",
        icon="mdi:volume-mute",
        ssc_path=PATH_OUTPUT_MUTE,
    ),
    NeumannKHSwitchDescription(
        key="identify",
        translation_key="identify",
        icon="mdi:led-on",
        ssc_path=PATH_IDENTIFY,
    ),
)

# Nur bei Nicht-Subwoofer-Modellen (nur dort schreibbar).
NON_SUBWOOFER_SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="phase_invert",
        translation_key="phase_invert",
        icon="mdi:sine-wave",
        ssc_path=PATH_OUTPUT_PHASE_INVERSION,
    ),
    NeumannKHSwitchDescription(
        key="auto_standby",
        translation_key="auto_standby",
        icon="mdi:power-sleep",
        ssc_path=PATH_STANDBY_ENABLED,
    ),
)

# Nur bei erkanntem Subwoofer.
SUBWOOFER_SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="out1_mute",
        translation_key="out1_mute",
        icon="mdi:volume-mute",
        entity_registry_enabled_default=False,  # nur relevant, falls Out1 belegt ist
        ssc_path=PATH_OUT1_MUTE,
    ),
    NeumannKHSwitchDescription(
        key="out2_mute",
        translation_key="out2_mute",
        icon="mdi:volume-mute",
        entity_registry_enabled_default=False,  # nur relevant, falls Out2 belegt ist
        ssc_path=PATH_OUT2_MUTE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Switch-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(COMMON_SWITCH_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) not in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.extend(NON_SUBWOOFER_SWITCH_DESCRIPTIONS)
    else:
        descriptions.extend(SUBWOOFER_SWITCH_DESCRIPTIONS)

    entities = [
        NeumannKHSwitch(coordinator, entry, description) for description in descriptions
    ]
    entities += [
        NeumannKHEQBandSwitch(coordinator, entry, description)
        for description in build_eq_switch_descriptions(entry.data.get(CONF_MODEL))
    ]
    async_add_entities(entities)


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
            confirmed = await self.coordinator.client.set(self.entity_description.ssc_path, value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self._apply_confirmed_value(self.entity_description.ssc_path, confirmed)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
