"""DataUpdateCoordinator for the Neumann KH (SSC) integration.

Queries each value individually on every poll cycle (one SSC message per
leaf path). Collective messages and container queries (e.g. {"device":null})
are rejected by the firmware - only individual, concrete leaf paths
work reliably.

Error handling: connection errors fail the whole cycle.
A rejected/faulty single path is skipped, the remaining values
are updated anyway. A time limit (POLL_CYCLE_TIMEOUT_SECONDS)
prevents a hanging device from blocking the cycle.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._util import build_nested, deep_merge
from .const import (
    MODELS_WITH_LOGO_AND_SAVE,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_LOGO_BRIGHTNESS,
    POLL_CYCLE_TIMEOUT_SECONDS,
    POLL_PATHS,
    SLOW_POLL_EVERY_N_CYCLES,
    SLOW_POLL_PATHS,
    SUBWOOFER_POLL_PATHS,
    SUBWOOFER_SLOW_POLL_PATHS,
    UPDATE_INTERVAL_SECONDS,
)
from .eq_containers import eq_containers_for_model
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)


class NeumannKHCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinates the polling of a single Neumann KH speaker."""

    def __init__(
        self, hass: HomeAssistant, client: SSCClient, name: str, model: str | None = None
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"neumann_kh_{name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.client = client
        self.model = model
        # Fast paths: every cycle. Slow paths: only every N cycles.
        self._poll_paths = list(POLL_PATHS)
        self._slow_poll_paths = list(SLOW_POLL_PATHS)
        # Logo brightness only on matching models (not KH 750 DSP).
        if model in MODELS_WITH_LOGO_AND_SAVE:
            self._poll_paths.append(PATH_LOGO_BRIGHTNESS)
        # Subwoofer-specific paths only on a detected subwoofer.
        if model in MODELS_WITH_SUBWOOFER_FEATURES:
            self._poll_paths.extend(SUBWOOFER_POLL_PATHS)
            self._slow_poll_paths.extend(SUBWOOFER_SLOW_POLL_PATHS)
        # EQ "enabled" arrays for the container on/off switches (see eq.py).
        # Change only through user action (which applies the confirmed value
        # immediately) - therefore in the slow poll.
        for container in eq_containers_for_model(model):
            self._slow_poll_paths.append(container.path + ("enabled",))
        # Counts the poll cycles to include the slow paths only every Nth round.
        # Starts at 0, so that the slow paths are queried right on the very first
        # cycle (values available immediately).
        self._cycle_count = 0
        # Cache of the last polled slow values - merged back in during the
        # fast cycles so that the associated entities do not
        # fall to "unknown" in between.
        self._slow_data: dict[str, Any] = {}
        # True as long as a due slow poll has not yet run SUCCESSFULLY.
        # If exactly the slow cycle fails (e.g. device
        # briefly offline), the next successful cycle picks up the slow
        # paths immediately, instead of running up to 5 minutes on the old
        # cache.
        self._slow_poll_pending = False
        # Set over all slow paths for the membership test in
        # apply_confirmed_value() (the list is complete at that point).
        self._slow_path_set: set[tuple[str, ...]] = set(self._slow_poll_paths)

    async def _async_update_data(self) -> dict[str, Any]:
        """Query each path individually; a rejected/faulty single path is skipped."""
        include_slow = (
            self._slow_poll_pending
            or self._cycle_count % SLOW_POLL_EVERY_N_CYCLES == 0
        )
        self._cycle_count += 1
        if include_slow:
            # Stays set until the slow poll succeeded (see below).
            self._slow_poll_pending = True

        paths = list(self._poll_paths)
        if include_slow:
            paths.extend(self._slow_poll_paths)

        try:
            merged = await asyncio.wait_for(
                self._poll_all_paths(paths), timeout=POLL_CYCLE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as err:
            raise UpdateFailed(
                f"Neumann KH: poll cycle exceeded the time limit of "
                f"{POLL_CYCLE_TIMEOUT_SECONDS}s"
            ) from err

        if include_slow:
            # Slow values polled freshly and successfully - refresh cache for
            # the next fast cycles, clear the catch-up flag.
            self._slow_poll_pending = False
            self._slow_data = {}
            for path in self._slow_poll_paths:
                value = SSCClient.extract(merged, path)
                if value is not None:
                    deep_merge(self._slow_data, build_nested(path, value))
        else:
            # Fast cycle: merge the last known slow values back in.
            deep_merge(merged, self._slow_data)

        return merged

    async def _poll_all_paths(self, paths: list[tuple[str, ...]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        reachable = False
        try:
            for path in paths:
                # Priority path: briefly yield to a waiting user action.
                if self.client.priority_waiting.is_set():
                    await asyncio.sleep(0.05)

                try:
                    value = await self.client.get(path)
                except SSCDeviceError:
                    # Path not supported by this device - skip.
                    reachable = True
                    _LOGGER.debug(
                        "Path %s is not supported by the device, skipping", path
                    )
                    continue
                except (SSCConnectionError, SSCTimeoutError):
                    # A connection problem affects the whole cycle, not just
                    # this one path - propagate to the outer
                    # handling, instead of logging the same error again for
                    # every remaining path and starting a new (also
                    # failing) connection attempt.
                    raise
                except Exception:  # noqa: BLE001 - a bug on one path should not drag down all values
                    _LOGGER.exception(
                        "Unexpected error while querying path %s, skipping", path
                    )
                    continue
                reachable = True
                deep_merge(merged, build_nested(path, value))
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise UpdateFailed(f"Neumann KH unreachable: {err}") from err

        if not reachable:
            raise UpdateFailed("Neumann KH: none of the queried properties were reachable")

        return merged

    def apply_confirmed_value(self, path: tuple[str, ...], value: Any) -> None:
        """Apply a single device-confirmed value directly into the data."""
        self.apply_confirmed_values([(path, value)])

    def apply_confirmed_values(
        self, values: list[tuple[tuple[str, ...], Any]]
    ) -> None:
        """Apply several device-confirmed values in one update.

        If a path is in the slow poll, the _slow_data cache is additionally
        updated. Without that, the next FAST cycle would overwrite the
        confirmed value again with the stale cache state - the value "snaps
        back" and would stay wrong until the next slow poll (up to 5 min).
        Only merge slow paths into the cache: conversely, a blanket merge
        would let a stale fast value from the cache overwrite fresh poll
        values.

        Batching matters for the restore, which confirms dozens of values at
        once: every call copies the whole data tree and notifies every entity
        of the device, so applying them one by one produced thousands of state
        changes for a single button press.
        """
        if not values:
            return
        new_data: dict[str, Any] = {}
        if self.data:
            deep_merge(new_data, self.data)
        for path, value in values:
            deep_merge(new_data, build_nested(path, value))
            if path in self._slow_path_set:
                deep_merge(self._slow_data, build_nested(path, value))
        self.async_set_updated_data(new_data)

    def value(self, path: tuple[str, ...]) -> Any:
        """Convenient access to a value from the last polled data."""
        if self.data is None:
            return None
        return SSCClient.extract(self.data, path)
