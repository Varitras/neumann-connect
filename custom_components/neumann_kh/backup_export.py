"""Backup snapshot: all known values (writable settings plus
diagnostics/identity), without live readings (they change constantly,
not a meaningful part of a settings snapshot).
"""

from __future__ import annotations

from typing import Any

from ._util import build_nested, deep_merge
from .const import (
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_METER_CLIP,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_METER_OUTPUT_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    POLL_PATHS,
    SUBWOOFER_POLL_PATHS,
)
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

# Live readings: intentionally not included in the backup.
_EXCLUDED_PATHS = {
    PATH_METER_INPUT_LEVEL,
    PATH_METER_CLIP,
    PATH_METER_OUTPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_STANDBY_COUNTDOWN,
}


async def async_build_backup(client: SSCClient, model: str | None) -> dict[str, Any]:
    """Query all known values (except live readings) and return a JSON dict."""
    paths = list(POLL_PATHS)
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        paths += list(SUBWOOFER_POLL_PATHS)

    result: dict[str, Any] = {}
    for path in paths:
        if path in _EXCLUDED_PATHS:
            continue
        try:
            value = await client.get(path)
        except SSCDeviceError:
            continue
        except (SSCConnectionError, SSCTimeoutError):
            raise
        except Exception:  # noqa: BLE001 - a bug on one path should not abort the backup
            continue
        if value is not None:
            deep_merge(result, build_nested(path, value))

    return result
