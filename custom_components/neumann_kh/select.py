"""Select-Entities: feste Wertauswahlen (String-Enums).

"Steuerungsmodus" (NETWORK/LOCAL) bleibt immer deaktiviert: Wechsel zu LOCAL
kappt die Netzwerksteuerung bis zur manuellen Rückstellung am Gerät.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BASS_GAIN_OPTIONS,
    CONF_MODEL,
    CONTROL_MODE_OPTIONS,
    DOMAIN,
    INPUT_INTERFACE_OPTIONS,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_UI_BASS_GAIN,
    PATH_UI_CONTROL_MODE,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSelectDescription(SelectEntityDescription):
    """Beschreibung einer Select-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


# Immer angelegt, bewusst immer deaktiviert (Sicherheits-Ausnahme).
CONTROL_MODE_DESCRIPTION = NeumannKHSelectDescription(
    key="control_mode",
    translation_key="control_mode",
    icon="mdi:network-outline",
    options=list(CONTROL_MODE_OPTIONS),
    entity_registry_enabled_default=False,
    ssc_path=PATH_UI_CONTROL_MODE,
)


def _build_input_interface_description(is_subwoofer: bool) -> NeumannKHSelectDescription:
    """Baut die 'Eingangs-Interface'-Beschreibung mit modellabhängigem Standard."""
    return NeumannKHSelectDescription(
        key="input_interface",
        translation_key="input_interface",
        icon="mdi:audio-input-stereo-minijack",
        options=list(INPUT_INTERFACE_OPTIONS),
        entity_registry_enabled_default=not is_subwoofer,
        ssc_path=PATH_INPUT_INTERFACE_TYPE,
    )


# Nur bei Nicht-Subwoofer-Modellen. Bass Gain per Test bestätigt schreibbar.
NON_SUBWOOFER_SELECT_DESCRIPTIONS: tuple[NeumannKHSelectDescription, ...] = (
    NeumannKHSelectDescription(
        key="bass_gain",
        translation_key="bass_gain",
        icon="mdi:sine-wave",
        options=list(BASS_GAIN_OPTIONS),
        ssc_path=PATH_UI_BASS_GAIN,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Select-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    is_subwoofer = entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES

    descriptions = [
        CONTROL_MODE_DESCRIPTION,
        _build_input_interface_description(is_subwoofer),
    ]
    if not is_subwoofer:
        descriptions.extend(NON_SUBWOOFER_SELECT_DESCRIPTIONS)

    async_add_entities(
        NeumannKHSelect(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSelect(NeumannKHEntity, SelectEntity):
    """Feste Auswahl (String-Enum) eines Neumann-KH-Lautsprechers."""

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
                f"Der Lautsprecher hat diese Auswahl abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self._apply_confirmed_value(self.entity_description.ssc_path, confirmed)
