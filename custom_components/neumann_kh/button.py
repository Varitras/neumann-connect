"""Button entities: 'Restore factory defaults', 'Create backup',
'Restore backup' and 'Run device discovery'.

'Restore factory defaults' and 'Restore backup' both overwrite device state,
so both use a two-step confirmation: the first press only arms it, a second
press within 30s carries it out. Button entities cannot show a modal dialog,
which is why it works this way.

'Create backup' and 'Run device discovery' store their result permanently
(see storage.py, per serial number) and additionally write a JSON file to
<config>/neumann_kh/. That folder is not served over HTTP - unlike
<config>/www/, which Home Assistant exposes under /local/ without any
authentication. The notification names the path as plain text rather than a
link, because the frontend routes a same-host link inside the app instead of
fetching it.
"""

from __future__ import annotations

import asyncio
import time

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.components.persistent_notification import (
    async_dismiss as async_dismiss_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ._util import localized
from .const import (
    CONF_MODEL,
    DOMAIN,
    PATH_RESTORE,
    RESTORE_FACTORY_DEFAULTS_VALUE,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .eq import build_eq_reset_buttons
from .export_actions import (
    async_check_restorable,
    async_run_backup,
    async_run_discovery,
    async_run_restore,
)
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

# Time window within which a second press of "factory reset" actually
# triggers the reset. After it elapses, it must be "armed" again.
_RESTORE_CONFIRM_WINDOW_SECONDS = 30


def _claim_device(coordinator: NeumannKHCoordinator) -> asyncio.Lock:
    """Refuse the press if another action already owns the device.

    Waiting would be worse than refusing: these actions are long and two of
    them rewrite the speaker, so a queued second press would fire minutes
    later on a device the user has stopped watching.
    """
    if coordinator.action_lock.locked():
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_action_in_progress",
        )
    return coordinator.action_lock


RESTORE_DESCRIPTION = ButtonEntityDescription(
    key="restore_factory_defaults",
    translation_key="restore_factory_defaults",
    icon="mdi:restore-alert",
    entity_registry_enabled_default=False,  # destructive action, deliberately not visible by default
)

BACKUP_DESCRIPTION = ButtonEntityDescription(
    key="create_backup",
    translation_key="create_backup",
    icon="mdi:content-save-cog-outline",
)

RESTORE_BACKUP_DESCRIPTION = ButtonEntityDescription(
    key="restore_backup",
    translation_key="restore_backup",
    icon="mdi:backup-restore",
    entity_registry_enabled_default=False,  # overwrites device settings, deliberately hidden
)

DISCOVERY_DESCRIPTION = ButtonEntityDescription(
    key="run_discovery",
    translation_key="run_discovery",
    icon="mdi:magnify-scan",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Creates the button entities for a speaker."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [
        NeumannKHRestoreButton(coordinator, entry),
        NeumannKHBackupButton(coordinator, entry),
        NeumannKHRestoreBackupButton(coordinator, entry),
        NeumannKHDiscoveryButton(coordinator, entry),
    ]
    entities += build_eq_reset_buttons(coordinator, entry, entry.data.get(CONF_MODEL))

    # A "save settings" button used to be added here for the monitor models.
    # "device/save_settings" is answered with a 404 on the KH 120 II, the only
    # test device that ever offered the button, so it could not have worked on
    # any speaker it was shown for.

    async_add_entities(entities)


class NeumannKHRestoreButton(NeumannKHEntity, ButtonEntity):
    """Factory reset with two-step confirmation (first 'arm', then confirm)."""

    entity_description = RESTORE_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_restore_factory_defaults"
        self._armed_at: float | None = None
        self._notification_id = f"{self._unique_id_base}_restore_confirm"

    async def async_press(self) -> None:
        now = time.monotonic()

        if self._armed_at is not None and (now - self._armed_at) <= _RESTORE_CONFIRM_WINDOW_SECONDS:
            # Second press within the time window -> actually trigger the reset.
            self._armed_at = None
            async_dismiss_notification(self.hass, self._notification_id)
            try:
                # The most destructive action of the four, and the only one
                # that never had a guard.
                async with _claim_device(self.coordinator):
                    await self.coordinator.client.set(
                        PATH_RESTORE, RESTORE_FACTORY_DEFAULTS_VALUE
                    )
            except SSCDeviceError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="factory_reset_rejected",
                    translation_placeholders={"error": str(err)},
                ) from err
            except (SSCConnectionError, SSCTimeoutError) as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_unreachable",
                    translation_placeholders={"error": str(err)},
                ) from err
            # A reset rewrites everything at once, so every cached value is
            # stale - including the slow-polled ones, which would otherwise
            # keep showing pre-reset settings for up to five minutes.
            await self.coordinator.async_invalidate_and_refresh()
            return

        # First press (or time window elapsed) -> only "arm" and warn.
        self._armed_at = now
        async_create_notification(
            self.hass,
            localized(
                self.hass.config.language,
                (
                    f"⚠️ Werksreset für **{self._entry.title}** ist jetzt bereit. "
                    f"Drücke den Button innerhalb von {_RESTORE_CONFIRM_WINDOW_SECONDS} Sekunden "
                    f"ERNEUT, um alle Einstellungen unwiderruflich auf Werkszustand "
                    f"zurückzusetzen. Ohne zweiten Druck passiert nichts."
                ),
                (
                    f"⚠️ Factory reset for **{self._entry.title}** is now armed. "
                    f"Press the button AGAIN within {_RESTORE_CONFIRM_WINDOW_SECONDS} seconds "
                    f"to irreversibly reset all settings to factory state. "
                    f"Nothing happens without a second press."
                ),
            ),
            title=localized(
                self.hass.config.language,
                "Neumann Connect: Werksreset bestätigen",
                "Neumann Connect: confirm factory reset",
            ),
            notification_id=self._notification_id,
        )


class NeumannKHBackupButton(NeumannKHEntity, ButtonEntity):
    """Reads all known values (without live measurements) and saves them as a backup."""

    entity_description = BACKUP_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_create_backup"

    async def async_press(self) -> None:
        async with _claim_device(self.coordinator):
            await async_run_backup(self.hass, self._entry, self.coordinator.client)


class NeumannKHDiscoveryButton(NeumannKHEntity, ButtonEntity):
    """Runs a full device discovery and saves the result."""

    entity_description = DISCOVERY_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_run_discovery"

    async def async_press(self) -> None:
        async with _claim_device(self.coordinator):
            await async_run_discovery(self.hass, self._entry, self.coordinator.client)


class NeumannKHRestoreBackupButton(NeumannKHEntity, ButtonEntity):
    """Writes the stored backup back to the device, with two-step confirmation.

    Like the factory reset, this overwrites device settings and cannot be
    undone, so the first press only arms it. Button entities cannot show a
    modal dialog, hence the same two-click pattern.
    """

    entity_description = RESTORE_BACKUP_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_restore_backup"
        self._armed_at: float | None = None
        self._armed_backup: dict | None = None
        self._notification_id = f"{self._unique_id_base}_restore_backup_confirm"

    async def async_press(self) -> None:
        now = time.monotonic()
        if self._armed_at is not None and (now - self._armed_at) <= _RESTORE_CONFIRM_WINDOW_SECONDS:
            armed_backup = self._armed_backup
            self._armed_at = None
            self._armed_backup = None
            async_dismiss_notification(self.hass, self._notification_id)
            # Restore exactly what was confirmed. Re-reading here would pick
            # up a backup created between the two presses, so the user would
            # confirm one snapshot and get another.
            async with _claim_device(self.coordinator):
                await async_run_restore(
                    self.hass, self._entry, self.coordinator, armed_backup
                )
            return

        # First press: validate before arming, so a mismatched or missing
        # backup is reported now rather than after a confirmation the user
        # cannot act on.
        backup = await async_check_restorable(self.hass, self._entry)
        self._armed_at = now
        self._armed_backup = backup
        async_create_notification(
            self.hass,
            localized(
                self.hass.config.language,
                f"Backup vom {backup.get('timestamp', '?')} für **{self._entry.title}** "
                f"zurückspielen? Innerhalb von {_RESTORE_CONFIRM_WINDOW_SECONDS} Sekunden "
                "erneut drücken. Die aktuellen Geräteeinstellungen werden überschrieben.",
                f"Restore the backup from {backup.get('timestamp', '?')} to "
                f"**{self._entry.title}**? Press again within "
                f"{_RESTORE_CONFIRM_WINDOW_SECONDS} seconds. The device's current settings "
                "will be overwritten.",
            ),
            title=localized(
                self.hass.config.language,
                "Neumann Connect: Zurückspielen bestätigen",
                "Neumann Connect: confirm restore",
            ),
            notification_id=self._notification_id,
        )
