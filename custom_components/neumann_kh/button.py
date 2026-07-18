"""Button entities: 'Save settings', 'Restore factory defaults',
'Create backup' and 'Run device discovery'.

'Save settings' only on KH 80/150/120 II (not KH 750; non-functional on
KH 120 II per test, therefore disabled by default).

'Restore factory defaults' with two-step confirmation: the first press only
arms it, a second press within 30s triggers the reset.

'Create backup' and 'Run device discovery' store their result permanently
(see storage.py, per serial number). The notification links to it via a
signed, time-limited URL served by the authenticated view in export_view.py -
nothing is written to disk.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
    async_dismiss as async_dismiss_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import storage
from .backup_export import async_build_backup
from .const import (
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_RESTORE,
    PATH_SAVE_SETTINGS,
    RESTORE_FACTORY_DEFAULTS_VALUE,
)
from .coordinator import NeumannKHCoordinator
from .discovery_export import async_discover_all_values
from .entity import NeumannKHEntity
from .export_view import EXPORT_KIND_BACKUP, EXPORT_KIND_DISCOVERY, async_export_path
from .eq import build_eq_reset_buttons
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

# Time window within which a second press of "factory reset" actually
# triggers the reset. After it elapses, it must be "armed" again.
_RESTORE_CONFIRM_WINDOW_SECONDS = 30

# Lifetime of a signed export download link. Long enough to notice the
# notification and click it, short enough that a stale link in an old
# notification stops working.
EXPORT_LINK_VALID_SECONDS = 3600


def _localized(hass: HomeAssistant, de: str, en: str) -> str:
    """Pick the German or English text based on the HA UI language.

    Persistent notifications have no translation_key mechanism, so their
    text is chosen here at runtime from the configured HA language.
    """
    language = hass.config.language or "en"
    return de if language.startswith("de") else en


SAVE_SETTINGS_DESCRIPTION = ButtonEntityDescription(
    key="save_settings",
    translation_key="save_settings",
    icon="mdi:content-save-outline",
    entity_registry_enabled_default=False,  # non-functional per test (KH 120 II)
)

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
        NeumannKHDiscoveryButton(coordinator, entry),
    ]
    entities += build_eq_reset_buttons(coordinator, entry, entry.data.get(CONF_MODEL))
    if entry.data.get(CONF_MODEL) in MODELS_WITH_LOGO_AND_SAVE:
        entities.append(NeumannKHSaveSettingsButton(coordinator, entry))

    async_add_entities(entities)


def _mask_serial(serial: str) -> str:
    """Masks a serial number, only the last 3 characters remain visible."""
    if len(serial) <= 3:
        return serial
    return "x" * (len(serial) - 3) + serial[-3:]


def _signed_export_url(hass: HomeAssistant, entry: ConfigEntry, kind: str) -> str:
    """Build a time-limited, signed download URL for a stored export.

    The export is served by an authenticated view (see export_view.py). Signing
    the path lets a click in a persistent notification work in the browser,
    which cannot send an Authorization header, without exposing the endpoint.
    The link expires; the data stays in the store, so pressing the button again
    produces a fresh link.
    """
    return async_sign_path(
        hass,
        async_export_path(entry, kind),
        timedelta(seconds=EXPORT_LINK_VALID_SECONDS),
    )


class NeumannKHSaveSettingsButton(NeumannKHEntity, ButtonEntity):
    """Writes the current settings permanently to the device (survives power loss)."""

    entity_description = SAVE_SETTINGS_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_save_settings"

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.set(PATH_SAVE_SETTINGS, True)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="save_settings_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err


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
                await self.coordinator.client.set(PATH_RESTORE, RESTORE_FACTORY_DEFAULTS_VALUE)
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
            return

        # First press (or time window elapsed) -> only "arm" and warn.
        self._armed_at = now
        async_create_notification(
            self.hass,
            _localized(
                self.hass,
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
            title=_localized(
                self.hass,
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
        self._running = False

    async def async_press(self) -> None:
        if self._running:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="backup_in_progress",
            )
        self._running = True
        try:
            serial = self._entry.data.get(CONF_SERIAL) or self._entry.entry_id
            model = self._entry.data.get(CONF_MODEL)

            try:
                values = await async_build_backup(self.coordinator.client, model)
            except Exception as err:  # noqa: BLE001 - backup/discovery are best-effort
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="backup_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

            # The exported content carries a masked serial number only; the
            # store is still keyed by the real one (mapping/retrieval).
            masked_serial = _mask_serial(serial)
            timestamp = datetime.now(timezone.utc).isoformat()
            backup = {
                "timestamp": timestamp,
                "model": model,
                "serial": masked_serial,
                "values": values,
            }

            await storage.async_save_backup(self.hass, serial, backup)
            url = _signed_export_url(self.hass, self._entry, EXPORT_KIND_BACKUP)

            async_create_notification(
                self.hass,
                _localized(
                    self.hass,
                    f"Backup für **{self._entry.title}** gespeichert. "
                    f"[Download]({url}) – Link 1 Stunde gültig, danach Button erneut drücken.",
                    f"Backup for **{self._entry.title}** saved. "
                    f"[Download]({url}) – link valid for 1 hour, press the button again afterwards.",
                ),
                title=_localized(
                    self.hass,
                    "Neumann Connect: Backup erstellt",
                    "Neumann Connect: backup created",
                ),
                notification_id=f"{self._unique_id_base}_backup_done",
            )
        finally:
            self._running = False


class NeumannKHDiscoveryButton(NeumannKHEntity, ButtonEntity):
    """Runs a full device discovery and saves the result."""

    entity_description = DISCOVERY_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_run_discovery"
        self._running = False

    async def async_press(self) -> None:
        if self._running:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="discovery_in_progress",
            )
        self._running = True
        try:
            serial = self._entry.data.get(CONF_SERIAL) or self._entry.entry_id

            try:
                discovery = await async_discover_all_values(self.coordinator.client)
            except Exception as err:  # noqa: BLE001 - backup/discovery are best-effort
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="discovery_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

            masked_serial = _mask_serial(serial)
            timestamp = datetime.now(timezone.utc).isoformat()
            record = {
                "timestamp": timestamp,
                "model": self._entry.data.get(CONF_MODEL),
                "serial": masked_serial,
                **discovery,
            }

            # Storage internally uses the real serial number (mapping/retrieval),
            # but the exported content contains only the masked variant.
            await storage.async_save_discovery(self.hass, serial, record)
            url = _signed_export_url(self.hass, self._entry, EXPORT_KIND_DISCOVERY)

            async_create_notification(
                self.hass,
                _localized(
                    self.hass,
                    f"Discovery für **{self._entry.title}** gespeichert. "
                    f"[Download]({url}) – Link 1 Stunde gültig, danach Button erneut drücken.",
                    f"Discovery for **{self._entry.title}** saved. "
                    f"[Download]({url}) – link valid for 1 hour, press the button again afterwards.",
                ),
                title=_localized(
                    self.hass,
                    "Neumann Connect: Discovery abgeschlossen",
                    "Neumann Connect: discovery finished",
                ),
                notification_id=f"{self._unique_id_base}_discovery_done",
            )
        finally:
            self._running = False
