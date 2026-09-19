"""A long operation publishes a snapshot older than something confirmed meanwhile.

The coordinator owns this invariant for one cell already: a value the device
confirms while a poll runs is applied over the poll's result (1.18.1b5). Two
cells of the same matrix were still open:

* A restore collects confirmations and applies them in one batch at the end.
  A rename that reached the device AFTER the restore wrote the name was then
  overwritten in Home Assistant by the batch - the speaker carried B, the
  entity showed A until the next slow poll, up to five minutes.
* A factory reset drops the slow cache and asks for a fresh poll. A slow poll
  that was already running wrote its pre-reset snapshot into the cache
  afterwards and published it - the reset looked undone.

What decides is the order of writes on the device, not the order in which
Home Assistant hears about them. Each interleaving below places the competing
change exactly into the window; nothing here runs in parallel by chance.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import export_actions
from custom_components.neumann_kh._util import build_nested, deep_merge
from custom_components.neumann_kh.backup_export import restorable_paths_for_model
from custom_components.neumann_kh.const import (
    CONF_MODEL,
    PATH_DEVICE_NAME,
    PATH_OUTPUT_MUTE,
    SLOW_POLL_EVERY_N_CYCLES,
)
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.export_actions import async_run_restore

_MODEL = "KH 120 II"
_RESTORED_NAME = "A"
_RENAMED_TO = "B"


class _Device:
    """Echoes writes, serves reads from `values`, and runs a hook around set()."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, ...], Any] = {
            PATH_OUTPUT_MUTE: False,
            PATH_DEVICE_NAME: "Before",
        }
        self.priority_waiting = asyncio.Event()
        self.after_set: dict[tuple[str, ...], Any] = {}
        self.hold_first_read_of: tuple[str, ...] | None = None
        self.release = asyncio.Event()
        self.held = asyncio.Event()

    async def get(self, path, priority: bool = False):
        value = self.values.get(path)
        if path == self.hold_first_read_of:
            # The snapshot is taken before the wait, like a real read that has
            # already left the device and is merely late to be processed.
            self.hold_first_read_of = None
            self.held.set()
            await self.release.wait()
        return value

    async def set(self, path, value, priority: bool = False):
        self.values[path] = value
        hook = self.after_set.pop(path, None)
        if hook is not None:
            hook()
        return value


class _Entry:
    def __init__(self) -> None:
        self.data = {CONF_MODEL: _MODEL}
        self.title = "Speaker"
        self.entry_id = "entry1"


@pytest.fixture(autouse=True)
def _no_notification(monkeypatch):
    monkeypatch.setattr(export_actions, "_notify", lambda *args, **kwargs: None)


@pytest.fixture
def device() -> _Device:
    return _Device()


@pytest.fixture
def coordinator(hass, device) -> NeumannKHCoordinator:
    coordinator = NeumannKHCoordinator(hass, device, "test", model=_MODEL)
    coordinator.update_interval = None
    return coordinator


def _backup() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path in restorable_paths_for_model(_MODEL):
        deep_merge(values, build_nested(path, 1))
    deep_merge(values, build_nested(PATH_DEVICE_NAME, _RESTORED_NAME))
    return {"values": values}


def _rename_via_entity(coordinator, device) -> None:
    """What text.async_set_value does once its own set() has returned."""
    device.values[PATH_DEVICE_NAME] = _RENAMED_TO
    coordinator.apply_confirmed_value(PATH_DEVICE_NAME, _RENAMED_TO)


def _path_written_after(path: tuple[str, ...]) -> tuple[str, ...]:
    order = restorable_paths_for_model(_MODEL)
    return order[order.index(path) + 1]


def _path_written_before(path: tuple[str, ...]) -> tuple[str, ...]:
    order = restorable_paths_for_model(_MODEL)
    return order[order.index(path) - 1]


async def test_a_rename_after_the_restore_wrote_the_name_survives_the_batch(
    hass, coordinator, device
):
    await coordinator.async_refresh()
    # The restore has just written the name; the rename lands on the device
    # while the restore is busy with the next path.
    device.after_set[_path_written_after(PATH_DEVICE_NAME)] = lambda: _rename_via_entity(
        coordinator, device
    )

    await async_run_restore(hass, _Entry(), coordinator, backup=_backup())

    assert device.values[PATH_DEVICE_NAME] == _RENAMED_TO
    assert coordinator.value(PATH_DEVICE_NAME) == _RENAMED_TO, (
        "the batch published the restored name over a rename the device already carries"
    )


async def test_a_rename_before_the_restore_wrote_the_name_is_overwritten_by_it(
    hass, coordinator, device
):
    """The other cell: here the restore's write is the newer one on the device."""
    await coordinator.async_refresh()
    device.after_set[_path_written_before(PATH_DEVICE_NAME)] = lambda: _rename_via_entity(
        coordinator, device
    )

    await async_run_restore(hass, _Entry(), coordinator, backup=_backup())

    assert device.values[PATH_DEVICE_NAME] == _RESTORED_NAME
    assert coordinator.value(PATH_DEVICE_NAME) == _RESTORED_NAME


async def test_a_reset_during_a_slow_poll_is_not_undone_by_it(hass, coordinator, device):
    await coordinator.async_refresh()  # cycle 0: slow, caches "Before"
    for _ in range(SLOW_POLL_EVERY_N_CYCLES - 1):
        await coordinator.async_refresh()  # fast cycles up to the next slow one

    # The next slow poll reads the name and is then held before it returns.
    device.hold_first_read_of = PATH_DEVICE_NAME
    stale_poll = asyncio.get_running_loop().create_task(coordinator.async_refresh())
    await asyncio.wait_for(device.held.wait(), timeout=5)

    # Factory reset while that poll is in flight: the device now says
    # "Factory", the cache is dropped and a fresh poll is requested. Home
    # Assistant serialises refreshes, so the request queues behind the poll
    # that is still running - and that poll returns first, with its
    # pre-reset snapshot.
    device.values[PATH_DEVICE_NAME] = "Factory"
    await coordinator.async_invalidate_and_refresh()
    device.release.set()
    await stale_poll

    await coordinator.async_refresh()  # the poll the reset asked for

    assert coordinator.value(PATH_DEVICE_NAME) == "Factory", (
        "a slow poll that was already running wrote its pre-reset snapshot back"
    )
