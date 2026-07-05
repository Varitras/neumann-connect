"""Button-Entities: 'Einstellungen speichern' und 'Gerät identifizieren'.

'Einstellungen speichern' (device/save_settings) ist lt. khtool-Dokumentation
nur für KH 80 / KH 150 / KH 120 II verfügbar, NICHT für KH 750 DSP - daher
wird diese Entity nur bei passendem Modell angelegt.

'Gerät identifizieren' (device/identification/visual) lässt lt. SSC-
Konvention das Logo/die LEDs kurz blinken, um das physische Gerät zu finden
- ungefährlich, wird für alle Modelle angelegt.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_IDENTIFY,
    PATH_SAVE_SETTINGS,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError

SAVE_SETTINGS_DESCRIPTION = ButtonEntityDescription(
    key="save_settings",
    translation_key="save_settings",
    icon="mdi:content-save-outline",
)

IDENTIFY_DESCRIPTION = ButtonEntityDescription(
    key="identify",
    translation_key="identify",
    icon="mdi:led-on",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Button-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [NeumannKHIdentifyButton(coordinator, entry)]
    if entry.data.get(CONF_MODEL) in MODELS_WITH_LOGO_AND_SAVE:
        entities.append(NeumannKHSaveSettingsButton(coordinator, entry))

    async_add_entities(entities)


class NeumannKHSaveSettingsButton(NeumannKHEntity, ButtonEntity):
    """Schreibt die aktuellen Einstellungen dauerhaft ins Gerät (überlebt Stromausfall)."""

    entity_description = SAVE_SETTINGS_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_save_settings"

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.set(PATH_SAVE_SETTINGS, True)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat 'Einstellungen speichern' abgelehnt: {err}"
            ) from err


class NeumannKHIdentifyButton(NeumannKHEntity, ButtonEntity):
    """Lässt das Logo/die LEDs kurz blinken, um das physische Gerät zu finden."""

    entity_description = IDENTIFY_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_identify"

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.set(PATH_IDENTIFY, True)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat 'Identifizieren' abgelehnt: {err}"
            ) from err
