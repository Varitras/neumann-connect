"""Write backup and discovery exports to disk.

Files go to `<config>/neumann_kh/`, not to `<config>/www/`. The latter is
served by Home Assistant under `/local/` without any authentication, so an
export placed there is readable by anyone who can reach the instance. This
folder is reachable through the file editor or a share, never over HTTP.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

EXPORT_DIR_NAME = "neumann_kh"


def _sanitize_filename_part(value: str) -> str:
    """Reduce a device-supplied value to [A-Za-z0-9_-].

    Guards against path components such as "../" coming from a faulty or
    manipulated device response - an export must never escape the export
    folder.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", value) or "unknown"


def _write(hass: HomeAssistant, filename: str, payload: dict[str, Any]) -> str:
    """Blocking write; returns the full path."""
    directory = hass.config.path(EXPORT_DIR_NAME)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    return path


async def async_write_export(
    hass: HomeAssistant, kind: str, name_part: str, payload: dict[str, Any]
) -> str:
    """Write an export out and return the path. File I/O runs in an executor."""
    filename = f"{EXPORT_DIR_NAME}_{kind}_{_sanitize_filename_part(name_part)}.json"
    path = await hass.async_add_executor_job(_write, hass, filename, payload)
    _LOGGER.debug("Wrote %s export to %s", kind, path)
    return path
