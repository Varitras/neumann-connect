"""Backup snapshot: all known values (writable settings plus
diagnostics/identity), without live readings (they change constantly,
not a meaningful part of a settings snapshot).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._util import build_nested, deep_merge
from .const import (
    DEVICE_ACTION_TIMEOUT_SECONDS,
    MODELS_WITH_LOGO_BRIGHTNESS,
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
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_COUNTDOWN,
    PATH_STANDBY_ENABLED,
    PATH_STANDBY_LEVEL,
    PATH_UI_CONTROL_MODE,
)
from .coordinator import poll_paths_for_model
from .eq_containers import eq_leaf_paths
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

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
    fast, slow = poll_paths_for_model(model)
    return fast + slow + list(eq_leaf_paths(model))


# Paths a restore may write, per model. This is an allowlist on purpose: a
# backup also holds identity, diagnostics, live readings and command paths, and
# "the device will reject what it should not accept" is no safeguard - the
# dangerous paths are exactly the writable ones.
#
# Deliberately NOT in here:
# - device/restore        the factory reset command
# - device/identification/visual  momentary action; restoring a captured
#                         "true" would leave the speaker blinking
_RESTORABLE_COMMON = (
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
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
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        paths += list(_RESTORABLE_SUBWOOFER)
    else:
        # Auto standby is writable on the monitors and read-only on the
        # subwoofer, which is why it is a switch on one and a binary sensor on
        # the other (see switch.py / binary_sensor.py). Writing it there only
        # earns a rejection. Phase inversion is the same story one step
        # further: the KH 750 answers that path with a 404.
        paths.append(PATH_STANDBY_ENABLED)
        paths.append(PATH_OUTPUT_PHASE_INVERSION)
    if model in MODELS_WITH_LOGO_BRIGHTNESS:
        paths.append(PATH_LOGO_BRIGHTNESS)
    paths += list(eq_leaf_paths(model))
    paths.append(PATH_UI_CONTROL_MODE)
    return paths


class BackupTimeoutError(Exception):
    """The run did not finish within DEVICE_ACTION_TIMEOUT_SECONDS."""


async def async_build_backup(client: SSCClient, model: str | None) -> dict[str, Any]:
    """Query all known values (except live readings) and return a JSON dict.

    Gives up once the time limit is reached instead of returning what it has:
    a partial snapshot is more dangerous than none, because it looks complete
    and would replace the last usable one.
    """
    paths = [path for path in known_paths_for_model(model) if path not in _EXCLUDED_PATHS]
    return await async_read_paths(client, paths, BackupTimeoutError)


async def async_read_paths(
    client: SSCClient, paths: list[tuple[str, ...]], timeout_error: type[Exception]
) -> dict[str, Any]:
    """Read each path on its own and merge the answers into one tree.

    Shared by the backup and the discovery. A path the device rejects is
    skipped; a lost connection or the time limit aborts the run, because a
    half-read snapshot looks complete and would replace the last good one.
    """
    result: dict[str, Any] = {}
    deadline = asyncio.get_running_loop().time() + DEVICE_ACTION_TIMEOUT_SECONDS
    for path in paths:
        if asyncio.get_running_loop().time() >= deadline:
            raise timeout_error(
                f"reading the values took longer than {DEVICE_ACTION_TIMEOUT_SECONDS:.0f}s"
            )
        try:
            value = await client.get(path)
        except SSCDeviceError:
            continue
        except SSCConnectionError, SSCTimeoutError:
            raise
        except Exception:
            # A bug on one path should not abort the run, but swallowing it
            # silently would leave a value missing from the file with nothing
            # to explain it. Same handling as the poll cycle in coordinator.py.
            _LOGGER.exception("Unexpected error while reading path %s", path)
            continue
        if value is not None:
            deep_merge(result, build_nested(path, value))
    return result
