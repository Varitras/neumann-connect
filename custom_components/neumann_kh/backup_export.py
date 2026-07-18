"""Backup snapshot: all known values (writable settings plus
diagnostics/identity), without live readings (they change constantly,
not a meaningful part of a settings snapshot).
"""

from __future__ import annotations

from typing import Any

from ._util import build_nested, deep_merge
from .const import (
    MODELS_WITH_LOGO_AND_SAVE,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_LOGO_BRIGHTNESS,
    PATH_METER_CLIP,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_METER_OUTPUT_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    POLL_PATHS,
    SLOW_POLL_PATHS,
    SUBWOOFER_POLL_PATHS,
    SUBWOOFER_SLOW_POLL_PATHS,
)
from .eq_containers import eq_leaf_paths
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

# Live readings: intentionally not included in the backup.
_EXCLUDED_PATHS = {
    PATH_METER_INPUT_LEVEL,
    PATH_METER_CLIP,
    PATH_METER_OUTPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_STANDBY_COUNTDOWN,
}


def known_paths_for_model(model: str | None) -> list[tuple[str, ...]]:
    """Every path this integration knows about for a model.

    The poll cycle splits these into fast, slow and EQ paths for timing
    reasons; a snapshot has no such reason and needs all of them. Earlier
    versions exported only the fast paths, so the rear-panel switches, the
    device name and the entire EQ were silently missing - while the README
    promised "all known values".
    """
    paths = list(POLL_PATHS) + list(SLOW_POLL_PATHS)
    # Model-dependent extras the coordinator adds the same way - without this
    # the logo brightness was missing from every export.
    if model in MODELS_WITH_LOGO_AND_SAVE:
        paths.append(PATH_LOGO_BRIGHTNESS)
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        paths += list(SUBWOOFER_POLL_PATHS) + list(SUBWOOFER_SLOW_POLL_PATHS)
    paths += list(eq_leaf_paths(model))
    return paths


async def async_build_backup(client: SSCClient, model: str | None) -> dict[str, Any]:
    """Query all known values (except live readings) and return a JSON dict."""
    result: dict[str, Any] = {}
    for path in known_paths_for_model(model):
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
