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
    PATH_DEVICE_NAME,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_LOGO_BRIGHTNESS,
    PATH_METER_CLIP,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_METER_OUTPUT_LEVEL,
    PATH_OUT1_DELAY,
    PATH_OUT1_LEVEL,
    PATH_OUT1_MUTE,
    PATH_OUT2_DELAY,
    PATH_OUT2_LEVEL,
    PATH_OUT2_MUTE,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_RESTORE,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_COUNTDOWN,
    PATH_STANDBY_ENABLED,
    PATH_STANDBY_LEVEL,
    PATH_UI_CONTROL_MODE,
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
    # A command, not a setting. Restore already refuses to write it, but there
    # is no reason to carry it in the file either - two independent guards
    # beat one.
    PATH_RESTORE,
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


# Paths a restore may write, per model. This is an allowlist on purpose: a
# backup also holds identity, diagnostics, live readings and command paths, and
# "the device will reject what it should not accept" is no safeguard - the
# dangerous paths are exactly the writable ones.
#
# Deliberately NOT in here:
# - device/restore        the factory reset command
# - device/save_settings  commits to flash, a command rather than a setting
# - device/identification/visual  momentary action; restoring a captured
#                         "true" would leave the speaker blinking
_RESTORABLE_COMMON = (
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_DEVICE_NAME,
)

_RESTORABLE_SUBWOOFER = (
    PATH_OUT1_LEVEL,
    PATH_OUT1_DELAY,
    PATH_OUT1_MUTE,
    PATH_OUT2_LEVEL,
    PATH_OUT2_DELAY,
    PATH_OUT2_MUTE,
)


def restorable_paths_for_model(model: str | None) -> list[tuple[str, ...]]:
    """Ordered list of paths a restore may write for a model.

    ui/control_mode comes last on purpose. Its values are NETWORK and LOCAL; a
    backup taken in LOCAL would switch the speaker away from network control
    while we are still writing over the network. Writing it last means
    everything else has already landed even if that cuts us off.
    """
    paths = list(_RESTORABLE_COMMON)
    if model not in MODELS_WITH_SUBWOOFER_FEATURES:
        # Auto standby is writable on the monitors and read-only on the
        # subwoofer, which is why it is a switch on one and a binary sensor on
        # the other (see switch.py / binary_sensor.py). Writing it there only
        # earns a rejection.
        paths.append(PATH_STANDBY_ENABLED)
    if model in MODELS_WITH_LOGO_AND_SAVE:
        paths.append(PATH_LOGO_BRIGHTNESS)
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        paths += list(_RESTORABLE_SUBWOOFER)
    paths += list(eq_leaf_paths(model))
    paths.append(PATH_UI_CONTROL_MODE)
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
