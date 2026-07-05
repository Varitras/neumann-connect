"""Button-Entity: 'Einstellungen speichern' (device/save_settings).

Lt. khtool-Dokumentation nur für KH 80 / KH 150 / KH 120 II verfügbar,
NICHT für KH 750 DSP - daher wird diese Entity nur bei passendem Modell
angelegt.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MODEL, DOMAIN, MODELS_WITH_LOGO_AND_SAVE, PATH_SAVE_SETTINGS
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity

SAVE_SETTINGS_DESCRIPTION = ButtonEntityDescription(
    key="save_settings",
    translation_key="save_settings",
    icon="mdi:content-save-outline",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt den 'Einstellungen speichern'-Button an, sofern vom Modell unterstützt."""
    if entry.data.get(CONF_MODEL) not in MODELS_WITH_LOGO_AND_SAVE:
        return

    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NeumannKHSaveSettingsButton(coordinator, entry)])


class NeumannKHSaveSettingsButton(NeumannKHEntity, ButtonEntity):
    """Schreibt die aktuellen Einstellungen dauerhaft ins Gerät (überlebt Stromausfall)."""

    entity_description = SAVE_SETTINGS_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_save_settings"

    async def async_press(self) -> None:
        await self.coordinator.client.set(PATH_SAVE_SETTINGS, True)
