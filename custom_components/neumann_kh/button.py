"""Button-Entities: 'Einstellungen speichern' und 'Werkseinstellungen wiederherstellen'.

'Einstellungen speichern' nur bei KH 80/150/120 II (nicht KH 750; auf KH 120 II
per Test nicht funktional, daher standardmäßig deaktiviert).

'Werkseinstellungen wiederherstellen' mit Zwei-Schritt-Sicherheitsabfrage:
erster Druck bewaffnet nur, zweiter Druck innerhalb 30s löst den Reset aus.
"""

from __future__ import annotations

import time

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
    async_dismiss as async_dismiss_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_RESTORE,
    PATH_SAVE_SETTINGS,
    RESTORE_FACTORY_DEFAULTS_VALUE,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError

# Zeitfenster, innerhalb dessen ein zweiter Druck auf "Werksreset" den
# Reset tatsächlich auslöst. Nach Ablauf muss erneut "bewaffnet" werden.
_RESTORE_CONFIRM_WINDOW_SECONDS = 30

SAVE_SETTINGS_DESCRIPTION = ButtonEntityDescription(
    key="save_settings",
    translation_key="save_settings",
    icon="mdi:content-save-outline",
    entity_registry_enabled_default=False,  # per Test nicht funktional (KH 120 II)
)

RESTORE_DESCRIPTION = ButtonEntityDescription(
    key="restore_factory_defaults",
    translation_key="restore_factory_defaults",
    icon="mdi:restore-alert",
    entity_registry_enabled_default=False,  # destruktive Aktion, bewusst nicht standardmäßig sichtbar
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Button-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [NeumannKHRestoreButton(coordinator, entry)]
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


class NeumannKHRestoreButton(NeumannKHEntity, ButtonEntity):
    """Werksreset mit Zwei-Schritt-Sicherheitsabfrage (erst 'bewaffnen', dann bestätigen)."""

    entity_description = RESTORE_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_restore_factory_defaults"
        self._armed_at: float | None = None
        self._notification_id = f"{self._unique_id_base}_restore_confirm"

    async def async_press(self) -> None:
        now = time.monotonic()

        if self._armed_at is not None and (now - self._armed_at) <= _RESTORE_CONFIRM_WINDOW_SECONDS:
            # Zweiter Druck innerhalb des Zeitfensters -> Reset tatsächlich auslösen.
            self._armed_at = None
            async_dismiss_notification(self.hass, self._notification_id)
            try:
                await self.coordinator.client.set(PATH_RESTORE, RESTORE_FACTORY_DEFAULTS_VALUE)
            except SSCDeviceError as err:
                raise HomeAssistantError(
                    f"Der Lautsprecher hat den Werksreset abgelehnt: {err}"
                ) from err
            return

        # Erster Druck (oder Zeitfenster abgelaufen) -> nur "bewaffnen" und warnen.
        self._armed_at = now
        async_create_notification(
            self.hass,
            (
                f"⚠️ Werksreset für **{self._entry.title}** ist jetzt bereit. "
                f"Drücke den Button innerhalb von {_RESTORE_CONFIRM_WINDOW_SECONDS} Sekunden "
                f"ERNEUT, um alle Einstellungen unwiderruflich auf Werkszustand "
                f"zurückzusetzen. Ohne zweiten Druck passiert nichts."
            ),
            title="Neumann Connect: Werksreset bestätigen",
            notification_id=self._notification_id,
        )
