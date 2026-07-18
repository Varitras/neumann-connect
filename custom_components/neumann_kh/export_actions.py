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
from .backup_export import async_build_backup
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
    path = await async_write_export(hass, KIND_BACKUP, masked, record)
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
    path = await async_write_export(hass, KIND_DISCOVERY, masked, record)
    _notify_written(hass, entry, KIND_DISCOVERY, path)
    return path


# --- Restore ---------------------------------------------------------------


def _leaf_paths(node: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Flatten a stored value tree into (path, value) pairs.

    A leaf is anything that is not a dict; EQ values are lists (one entry per
    band) and are written back as a whole, exactly as they were read.
    """
    if not isinstance(node, dict):
        return [(prefix, node)]
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, value in node.items():
        leaves.extend(_leaf_paths(value, prefix + (key,)))
    return leaves


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
    hass: HomeAssistant, entry: ConfigEntry, coordinator: Any
) -> tuple[int, int]:
    """Write a stored backup back to the device.

    Returns (written, skipped). A backup also contains values that are not
    writable (identity, diagnostics); the device rejects those with an SSC
    error and they are counted as skipped rather than failing the whole
    restore. A connection loss does abort - continuing would leave the device
    half-restored without saying so.

    Takes the coordinator rather than the client because the entities have to
    be refreshed afterwards: nothing else notices that the values changed, so
    the UI would keep showing the pre-restore state until the next poll.
    """
    backup = await async_check_restorable(hass, entry)
    client = coordinator.client

    written = 0
    skipped = 0
    for path, value in _leaf_paths(backup["values"]):
        if value is None:
            skipped += 1
            continue
        try:
            await client.set(path, value)
        except SSCDeviceError:
            # Read-only on this model - expected for identity and diagnostics.
            skipped += 1
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        else:
            written += 1

    _LOGGER.debug("Restore for %s: %d written, %d skipped", entry.title, written, skipped)

    # Pull the device state in now instead of leaving stale values on screen.
    await coordinator.async_request_refresh()

    language = hass.config.language
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
            f"Backup für **{entry.title}** zurückgespielt: {written} Werte geschrieben, "
            f"{skipped} übersprungen (nicht schreibbar auf diesem Modell).",
            f"Backup restored for **{entry.title}**: {written} values written, "
            f"{skipped} skipped (not writable on this model).",
        ),
    )
    return written, skipped
