"""Write backup and discovery exports to disk.

Files go to `<config>/neumann_kh/`, not to `<config>/www/`. The latter is
served by Home Assistant under `/local/` without any authentication, so an
export placed there is readable by anyone who can reach the instance. This
folder is reachable through the file editor or a share, never over HTTP.
"""

from __future__ import annotations

import contextlib
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
    """Blocking write; returns the full path.

    Writes to a temporary file and replaces the target in one step, so an
    interrupted write (restart, power loss) leaves the previous export intact
    rather than a truncated file.
    """
    directory = hass.config.path(EXPORT_DIR_NAME)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise
    return path


async def async_write_export(
    hass: HomeAssistant,
    kind: str,
    name_part: str,
    payload: dict[str, Any],
    discriminator: str = "",
) -> str:
    """Write an export out and return the path. File I/O runs in an executor.

    The masked serial alone is not unique: two speakers whose serials share
    their length and last three characters mask to the same string and would
    overwrite each other's export. The config entry id disambiguates them.
    """
    name = _sanitize_filename_part(name_part)
    if discriminator:
        name = f"{name}_{_sanitize_filename_part(discriminator)}"
    filename = f"{EXPORT_DIR_NAME}_{kind}_{name}.json"
    path = await hass.async_add_executor_job(_write, hass, filename, payload)
    _LOGGER.debug("Wrote %s export to %s", kind, path)
    return path
