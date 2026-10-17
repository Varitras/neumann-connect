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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._util import build_nested, deep_merge, extract
from .const import (
    DOMAIN,
    MODELS_WITH_LOGO_BRIGHTNESS,
    MODELS_WITH_SUBWOOFER_FEATURES,
    NON_SUBWOOFER_POLL_PATHS,
    NON_SUBWOOFER_SLOW_POLL_PATHS,
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


def poll_paths_for_model(model: str | None) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """The (fast, slow) paths a model is polled for, EQ aside.

    The one answer to "which paths does this model have": the backup reads the
    same list plus every EQ leaf, so a path added here reaches both.
    """
    fast = list(POLL_PATHS)
    slow = list(SLOW_POLL_PATHS)
    # Logo brightness only on matching models (not KH 750 DSP).
    if model in MODELS_WITH_LOGO_BRIGHTNESS:
        fast.append(PATH_LOGO_BRIGHTNESS)
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        fast.extend(SUBWOOFER_POLL_PATHS)
        slow.extend(SUBWOOFER_SLOW_POLL_PATHS)
    else:
        # Paths the subwoofer answers with a 404 - asking it every cycle only
        # earns a rejection (see NON_SUBWOOFER_POLL_PATHS).
        fast.extend(NON_SUBWOOFER_POLL_PATHS)
        slow.extend(NON_SUBWOOFER_SLOW_POLL_PATHS)
    return fast, slow


class SpeakerUnreachable(UpdateFailed):
    """The speaker answered nothing at all - normal while it is switched off."""


class _OfflineIsNotAnError(logging.Filter):
    """Downgrade the coordinator's "device is gone" line from error to info.

    Home Assistant's own quality scale (log-when-unavailable) asks for info
    level, but DataUpdateCoordinator logs the first failed cycle at error and
    offers no way to configure that. A monitor switched off overnight would
    post a red entry every morning for the most ordinary state there is.

    The case is recognised by the exception object, which arrives unformatted
    in the record arguments; matching on the message text would not survive
    Home Assistant rewording its own line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        is_expected_offline = record.levelno == logging.ERROR and any(
            isinstance(argument, SpeakerUnreachable) for argument in record.args or ()
        )
        if not is_expected_offline:
            return True
        record.levelno = logging.INFO
        record.levelname = logging.getLevelName(logging.INFO)
        # The level check ran before this filter, at error level - so a logger
        # set to warning would otherwise still emit the downgraded line.
        return _LOGGER.isEnabledFor(logging.INFO)


_LOGGER.addFilter(_OfflineIsNotAnError())


# The coordinator travels on the config entry itself rather than in hass.data:
# Home Assistant types it, hands it to every platform, and drops it with the
# entry, so there is no dictionary to keep in step with the entry's lifetime.
type NeumannKHConfigEntry = ConfigEntry[NeumannKHCoordinator]


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
        # Held for a whole device action (every button that talks to the
        # speaker, the EQ reset included), not for a single request. The
        # client's lock serialises individual messages, which is not enough: a
        # backup running while a
        # restore writes reads some values from before and some from after,
        # and that mixed snapshot then replaces the last good one.
        #
        # Deliberately NOT taken by the poll cycle. Blocking it would drop
        # every entity to unavailable for the duration of a backup; the
        # client's priority mechanism already keeps user actions ahead of it.
        self.action_lock = asyncio.Lock()
        # Fast paths: every cycle. Slow paths: only every N cycles.
        self._poll_paths, self._slow_poll_paths = poll_paths_for_model(model)
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
        # A poll builds its snapshot independently of self.data, so a value the
        # device confirms WHILE it runs would be overwritten when it returns.
        # These two carry such values across the poll (see _async_update_data).
        self._poll_in_flight = False
        self._confirmed_during_poll: list[tuple[tuple[str, ...], Any]] = []
        # Bumped by every invalidation. A poll that started before one holds
        # a snapshot of the device as it no longer is; the counter lets it
        # notice that and keep its stale slow values out of the cache.
        self._cache_generation = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Query each path individually; a rejected/faulty single path is skipped."""
        include_slow = self._slow_poll_pending or self._cycle_count % SLOW_POLL_EVERY_N_CYCLES == 0
        self._cycle_count += 1
        if include_slow:
            # Stays set until the slow poll succeeded (see below).
            self._slow_poll_pending = True

        paths = list(self._poll_paths)
        if include_slow:
            paths.extend(self._slow_poll_paths)

        self._confirmed_during_poll = []
        self._poll_in_flight = True
        generation_at_start = self._cache_generation
        try:
            merged = await asyncio.wait_for(
                self._poll_all_paths(paths), timeout=POLL_CYCLE_TIMEOUT_SECONDS
            )
        except TimeoutError as err:
            raise UpdateFailed(
                f"Neumann KH: poll cycle exceeded the time limit of {POLL_CYCLE_TIMEOUT_SECONDS}s"
            ) from err
        finally:
            self._poll_in_flight = False

        # Anything the device confirmed while this cycle was reading is newer
        # than what the cycle saw, whichever path it was read on. Applied here,
        # BEFORE the slow cache is refreshed from `merged` below, so the stale
        # value cannot be written into the cache either.
        for path, value in self._confirmed_during_poll:
            deep_merge(merged, build_nested(path, value))
        self._confirmed_during_poll = []

        invalidated_meanwhile = generation_at_start != self._cache_generation
        if include_slow and invalidated_meanwhile:
            # A factory reset landed while this cycle was reading. Every slow
            # value it holds predates the reset: writing them into the cache
            # would undo the invalidation, and clearing the catch-up flag
            # would turn the poll the reset asked for into a fast one that
            # merges that stale cache straight back in. Keep the data as
            # it stands: on a Home Assistant that serialises refreshes it
            # is what this poll would have replaced anyway, and on one that
            # does not, the poll the reset asked for may already have
            # published the post-reset state - which this must not undo.
            if self.data is None:
                return merged
            return self.data

        if include_slow:
            self._refresh_slow_cache(merged)
        # Every cycle carries the last known slow values; a slow cycle has
        # just renewed them, a fast cycle merely repeats them.
        deep_merge(merged, self._slow_data)
        return merged

    def _refresh_slow_cache(self, merged: dict[str, Any]) -> None:
        """Take the slow values a successful slow cycle read into the cache."""
        self._slow_poll_pending = False
        # Updated in place rather than rebuilt. Emptying it first meant a
        # single path that happened to fail this round lost its value
        # everywhere - the entity dropped to unknown and stayed there until
        # the next slow cycle, up to five minutes later, over one missed
        # answer. Every value that did answer lands in the cache before the
        # cache is merged back, so a stale one cannot overwrite a fresh one.
        for path in self._slow_poll_paths:
            value = extract(merged, path)
            if value is not None:
                deep_merge(self._slow_data, build_nested(path, value))

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
                    _LOGGER.debug("Path %s is not supported by the device, skipping", path)
                    continue
                except (SSCConnectionError, SSCTimeoutError):
                    # A connection problem affects the whole cycle, not just
                    # this one path - propagate to the outer
                    # handling, instead of logging the same error again for
                    # every remaining path and starting a new (also
                    # failing) connection attempt.
                    raise
                except Exception:
                    _LOGGER.exception("Unexpected error while querying path %s, skipping", path)
                    continue
                reachable = True
                deep_merge(merged, build_nested(path, value))
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise SpeakerUnreachable(f"Neumann KH unreachable: {err}") from err

        if not reachable:
            raise UpdateFailed("Neumann KH: none of the queried properties were reachable")

        return merged

    def claim_device(self) -> asyncio.Lock:
        """Refuse the caller if another action already owns the device.

        Waiting would be worse than refusing: these actions are long and some
        of them rewrite the speaker, so a queued second press would fire
        minutes later on a device the user has stopped watching.

        Lives here rather than next to the buttons because the lock is this
        object's state and the EQ reset button - in another module that
        button.py already imports - needs it too.
        """
        if self.action_lock.locked():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_action_in_progress",
            )
        return self.action_lock

    def apply_confirmed_value(
        self, path: tuple[str, ...], value: Any, *, publish: bool = True
    ) -> None:
        """Apply a device-confirmed value directly into the data.

        `publish=False` takes the value into the data without notifying the
        entities yet; `async_update_listeners()` does that later. A restore
        applies each confirmation the moment the device gives it and publishes
        once at the end - every publish notifies every entity of the device,
        so publishing per path produced thousands of state changes for one
        press. Applying them all at the end instead let a rename that reached
        the device after the restore wrote the name be overwritten: the order
        the device was written in is the order the data must be applied in.

        If a path is in the slow poll, the _slow_data cache is additionally
        updated. Without that, the next FAST cycle would overwrite the
        confirmed value again with the stale cache state - the value "snaps
        back" and would stay wrong until the next slow poll (up to 5 min).
        Only merge slow paths into the cache: conversely, a blanket merge
        would let a stale fast value from the cache overwrite fresh poll
        values.
        """
        new_data: dict[str, Any] = {}
        if self.data:
            deep_merge(new_data, self.data)
        deep_merge(new_data, build_nested(path, value))
        if path in self._slow_path_set:
            deep_merge(self._slow_data, build_nested(path, value))
        if self._poll_in_flight:
            self._confirmed_during_poll.append((path, value))
        if publish:
            self.async_set_updated_data(new_data)
        else:
            self.data = new_data

    async def async_invalidate_and_refresh(self) -> None:
        """Drop every cached value and poll again, slow paths included.

        For changes that rewrite the whole device at once - a factory reset -
        rather than a single confirmed value. Without dropping the slow cache
        the next fast cycle would merge the pre-change values back in, and the
        rarely polled entities would show the old state for up to five minutes
        while the device had already moved on.
        """
        self._slow_data = {}
        self._slow_poll_pending = True
        self._cache_generation += 1
        await self.async_request_refresh()

    @callback
    def request_reread(self, path: tuple[str, ...]) -> None:
        """Make the next poll read `path` again, even if it is a slow path.

        For a write the device did not confirm: no echo, or the line dropped
        after the request went out. The device may hold the new value, but a
        plain refresh skips slow paths in nine of ten cycles and merges the
        cached old value back in.

        Scheduled, not awaited: the caller is a failed write that should
        report at once, or a restore whose loop must not run a whole poll -
        and publish it - halfway through.
        """
        if path in self._slow_path_set:
            self._slow_poll_pending = True
        self.hass.async_create_task(self.async_request_refresh())

    def value(self, path: tuple[str, ...]) -> Any:
        """Convenient access to a value from the last polled data."""
        if self.data is None:
            return None
        return extract(self.data, path)
