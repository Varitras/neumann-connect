"""Shared backup, discovery and restore runs behind the buttons."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import storage
from ._util import localized
from .backup_export import async_build_backup, restorable_paths_for_model
from .const import CONF_MODEL, CONF_SERIAL, DOMAIN
from .discovery_export import async_discover_all_values
from .export_file import async_write_export
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

KIND_BACKUP = "backup"
KIND_DISCOVERY = "discovery"


def mask_serial(serial: str) -> str:
    """Mask a serial number, leaving only the last 3 characters visible."""
    if len(serial) <= 3:
        return serial
    return "x" * (len(serial) - 3) + serial[-3:]


def _notify(hass: HomeAssistant, entry: ConfigEntry, kind: str, title: str, body: str) -> None:
    # Paths are rendered as code, never as a link: the frontend routes a
    # same-host link inside the app instead of fetching it, so a link would
    # silently do nothing.
    async_create_notification(
        hass, body, title=title, notification_id=f"{entry.entry_id}_{kind}_done"
    )


def _notify_written(hass: HomeAssistant, entry: ConfigEntry, kind: str, path: str) -> None:
    language = hass.config.language
    if kind == KIND_BACKUP:
        title = localized(
            language, "Neumann Connect: Backup erstellt", "Neumann Connect: backup created"
        )
        body = localized(
            language,
            f"Backup für **{entry.title}** gespeichert:\n\n`{path}`",
            f"Backup for **{entry.title}** saved:\n\n`{path}`",
        )
    else:
        title = localized(
            language,
            "Neumann Connect: Discovery abgeschlossen",
            "Neumann Connect: discovery finished",
        )
        body = localized(
            language,
            f"Discovery für **{entry.title}** gespeichert:\n\n`{path}`",
            f"Discovery for **{entry.title}** saved:\n\n`{path}`",
        )
    _notify(hass, entry, kind, title, body)


async def async_run_backup(
    hass: HomeAssistant, entry: ConfigEntry, client: SSCClient
) -> str:
    """Read all known values, store them and write them out."""
    serial = entry.data.get(CONF_SERIAL) or entry.entry_id
    model = entry.data.get(CONF_MODEL)

    try:
        values = await async_build_backup(client, model)
    except Exception as err:  # noqa: BLE001 - backup is best-effort
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    # The exported content carries a masked serial only; the store stays keyed
    # by the real one for mapping and retrieval.
    masked = mask_serial(serial)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "serial": masked,
        "values": values,
    }
    await storage.async_save_backup(hass, serial, record)
    path = await async_write_export(hass, KIND_BACKUP, masked, record, entry.entry_id)
    _notify_written(hass, entry, KIND_BACKUP, path)
    return path


async def async_run_discovery(
    hass: HomeAssistant, entry: ConfigEntry, client: SSCClient
) -> str:
    """Run a full device discovery, store it and write it out."""
    serial = entry.data.get(CONF_SERIAL) or entry.entry_id
    model = entry.data.get(CONF_MODEL)

    try:
        discovery = await async_discover_all_values(client, model)
    except Exception as err:  # noqa: BLE001 - discovery is best-effort
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="discovery_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    masked = mask_serial(serial)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "serial": masked,
        **discovery,
    }
    await storage.async_save_discovery(hass, serial, record)
    path = await async_write_export(hass, KIND_DISCOVERY, masked, record, entry.entry_id)
    _notify_written(hass, entry, KIND_DISCOVERY, path)
    return path


# --- Restore ---------------------------------------------------------------


def _value_at(values: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read a single leaf out of a stored value tree, or None if absent."""
    node: Any = values
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


async def async_check_restorable(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Load the stored backup for this entry and refuse a mismatched one.

    Writing one model's settings into another would push values the target has
    no concept of - or worse, values that mean something different there - so
    both the model and the (masked) serial have to match before anything is
    written.
    """
    serial = entry.data.get(CONF_SERIAL) or entry.entry_id
    backup = await storage.async_get_backup(hass, serial)
    if not backup or not backup.get("values"):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="restore_no_backup"
        )

    model = entry.data.get(CONF_MODEL)
    backup_model = backup.get("model")
    if backup_model and model and backup_model != model:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="restore_model_mismatch",
            translation_placeholders={"backup": backup_model, "device": model},
        )

    backup_serial = backup.get("serial")
    if backup_serial and backup_serial != mask_serial(serial):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="restore_serial_mismatch",
        )

    return backup


async def async_run_restore(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
    backup: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """Write a stored backup back to the device.

    Returns (written, adjusted, skipped). Only paths on the restore allowlist
    are written - a backup also holds identity, diagnostics and command paths,
    and relying on the device to reject those is no safeguard, because the
    dangerous ones are exactly the writable ones.

    `backup` is the record the user confirmed. The button passes the one it
    loaded when arming, so a backup created between the two presses cannot
    swap out what actually gets written.

    Takes the coordinator rather than the client because the entities have to
    be updated afterwards: nothing else notices that the values changed, so
    the UI would keep showing the pre-restore state until the next poll.
    """
    if backup is None:
        backup = await async_check_restorable(hass, entry)
    client = coordinator.client
    values = backup["values"]

    written = 0
    adjusted = 0
    skipped = 0
    confirmed_values: list[tuple[tuple[str, ...], Any]] = []

    for path in restorable_paths_for_model(entry.data.get(CONF_MODEL)):
        value = _value_at(values, path)
        if value is None:
            skipped += 1
            continue
        try:
            confirmed = await client.set(path, value)
        except SSCDeviceError:
            # Not writable on this model or firmware.
            skipped += 1
        except (SSCConnectionError, SSCTimeoutError) as err:
            # Everything written so far stays on the device. Say how far it
            # got instead of leaving the user with a half-restored speaker and
            # a bare "unreachable".
            if confirmed_values:
                coordinator.apply_confirmed_values(confirmed_values)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restore_interrupted",
                translation_placeholders={
                    "written": str(written + adjusted),
                    "error": str(err),
                },
            ) from err
        else:
            confirmed_values.append((path, confirmed))
            if confirmed != value:
                # The device clamped or normalised the value. Reporting it as
                # restored would be a lie.
                adjusted += 1
            else:
                written += 1

    # One update for the whole restore instead of one per path: each call
    # copies the coordinator data and notifies every entity of the device, so
    # per-path updates produced thousands of state changes for a single press.
    # apply_confirmed_values() also maintains the slow-poll cache - without
    # that, the next fast cycle would re-merge stale values and the restore
    # would snap back (see the 1.15.1 regression).
    if confirmed_values:
        coordinator.apply_confirmed_values(confirmed_values)

    _LOGGER.debug(
        "Restore for %s: %d written, %d adjusted, %d skipped",
        entry.title,
        written,
        adjusted,
        skipped,
    )

    language = hass.config.language
    adjusted_de = f", {adjusted} vom Gerät angepasst" if adjusted else ""
    adjusted_en = f", {adjusted} adjusted by the device" if adjusted else ""
    _notify(
        hass,
        entry,
        "restore",
        localized(
            language,
            "Neumann Connect: Backup zurückgespielt",
            "Neumann Connect: backup restored",
        ),
        localized(
            language,
            f"Backup für **{entry.title}** zurückgespielt: {written} Werte "
            f"geschrieben{adjusted_de}, {skipped} übersprungen.",
            f"Backup restored for **{entry.title}**: {written} values "
            f"written{adjusted_en}, {skipped} skipped.",
        ),
    )
    return written, adjusted, skipped
