"""Button-Entities: 'Einstellungen speichern', 'Werkseinstellungen wiederherstellen',
'Backup erstellen' und 'Geräte-Discovery ausführen'.

'Einstellungen speichern' nur bei KH 80/150/120 II (nicht KH 750; auf KH 120 II
per Test nicht funktional, daher standardmäßig deaktiviert).

'Werkseinstellungen wiederherstellen' mit Zwei-Schritt-Sicherheitsabfrage:
erster Druck bewaffnet nur, zweiter Druck innerhalb 30s löst den Reset aus.

'Backup erstellen' und 'Geräte-Discovery ausführen' speichern ihr Ergebnis
dauerhaft (siehe storage.py, pro Seriennummer) und zusätzlich als JSON-Datei
zum Download unter /config/www/.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
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
from .eq import build_eq_reset_buttons
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

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
    """Legt die Button-Entities für einen Lautsprecher an."""
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
    """Zensiert eine Seriennummer, nur die letzten 3 Zeichen bleiben sichtbar."""
    if len(serial) <= 3:
        return serial
    return "x" * (len(serial) - 3) + serial[-3:]


def _sanitize_filename_part(value: str) -> str:
    """Bereinigt gerätegelieferte Werte für Dateinamen (nur [A-Za-z0-9_-]).

    Schutz gegen Pfad-Bestandteile (z. B. "../") aus einer fehlerhaften oder
    manipulierten Geräteantwort - Exportdateien dürfen /config/www/ nie
    verlassen.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", value) or "unbekannt"


def _write_export_file(hass: HomeAssistant, filename: str, data: dict) -> str:
    """Schreibt ein JSON-Export unter /config/www/ und liefert die lokale URL."""
    www_dir = hass.config.path("www")
    os.makedirs(www_dir, exist_ok=True)
    path = os.path.join(www_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return f"/local/{filename}"


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
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(f"Der Lautsprecher ist nicht erreichbar: {err}") from err


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
            except (SSCConnectionError, SSCTimeoutError) as err:
                raise HomeAssistantError(
                    f"Der Lautsprecher ist nicht erreichbar: {err}"
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


class NeumannKHBackupButton(NeumannKHEntity, ButtonEntity):
    """Liest alle bekannten Werte (ohne Live-Messwerte) und speichert sie als Backup."""

    entity_description = BACKUP_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_create_backup"
        self._running = False

    async def async_press(self) -> None:
        if self._running:
            raise HomeAssistantError("Ein Backup läuft bereits, bitte warten.")
        self._running = True
        try:
            serial = self._entry.data.get(CONF_SERIAL) or self._entry.entry_id
            model = self._entry.data.get(CONF_MODEL)

            try:
                values = await async_build_backup(self.coordinator.client, model)
            except Exception as err:  # noqa: BLE001 - Backup/Discovery sind best-effort
                raise HomeAssistantError(f"Backup fehlgeschlagen: {err}") from err

            # Datei-Inhalt und Dateiname nur mit zensierter Seriennummer:
            # /config/www/ wird von HA OHNE Anmeldung ausgeliefert (/local/).
            # Die Speicherung im HA-Store läuft weiter über die echte
            # Seriennummer (Zuordnung/Abruf).
            masked_serial = _mask_serial(serial)
            timestamp = datetime.now(timezone.utc).isoformat()
            backup = {
                "timestamp": timestamp,
                "model": model,
                "serial": masked_serial,
                "values": values,
            }

            await storage.async_save_backup(self.hass, serial, backup)
            filename = f"neumann_kh_backup_{_sanitize_filename_part(masked_serial)}.json"
            url = await self.hass.async_add_executor_job(
                _write_export_file, self.hass, filename, backup
            )

            async_create_notification(
                self.hass,
                f"Backup für **{self._entry.title}** gespeichert. Download: {url}",
                title="Neumann Connect: Backup erstellt",
                notification_id=f"{self._unique_id_base}_backup_done",
            )
        finally:
            self._running = False


class NeumannKHDiscoveryButton(NeumannKHEntity, ButtonEntity):
    """Führt eine vollständige Geräte-Discovery aus und speichert das Ergebnis."""

    entity_description = DISCOVERY_DESCRIPTION

    def __init__(self, coordinator: NeumannKHCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._unique_id_base}_run_discovery"
        self._running = False

    async def async_press(self) -> None:
        if self._running:
            raise HomeAssistantError("Eine Discovery läuft bereits, bitte warten.")
        self._running = True
        try:
            serial = self._entry.data.get(CONF_SERIAL) or self._entry.entry_id

            try:
                discovery = await async_discover_all_values(self.coordinator.client)
            except Exception as err:  # noqa: BLE001 - Backup/Discovery sind best-effort
                raise HomeAssistantError(f"Discovery fehlgeschlagen: {err}") from err

            masked_serial = _mask_serial(serial)
            timestamp = datetime.now(timezone.utc).isoformat()
            record = {
                "timestamp": timestamp,
                "model": self._entry.data.get(CONF_MODEL),
                "serial": masked_serial,
                **discovery,
            }

            # Speicherung intern über die echte Seriennummer (Zuordnung/Abruf),
            # der Inhalt (und die Datei) enthält aber nur die zensierte Variante.
            await storage.async_save_discovery(self.hass, serial, record)
            filename = f"neumann_kh_discovery_{_sanitize_filename_part(masked_serial)}.json"
            url = await self.hass.async_add_executor_job(
                _write_export_file, self.hass, filename, record
            )

            async_create_notification(
                self.hass,
                f"Discovery für **{self._entry.title}** gespeichert. Download: {url}",
                title="Neumann Connect: Discovery abgeschlossen",
                notification_id=f"{self._unique_id_base}_discovery_done",
            )
        finally:
            self._running = False
