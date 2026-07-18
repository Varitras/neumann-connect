"""Tests for the coordinator logic: poll split, slow cache, pending flag.

In particular contains the regression tests for the value-snapping-back bug
(v1.15.1): device-confirmed values on slow paths must not be overwritten by
the next fast cycle with the stale cache.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.neumann_kh.const import (
    PATH_DEVICE_NAME,
    PATH_OUTPUT_MUTE,
    SLOW_POLL_PATHS,
)
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.ssc_client import SSCConnectionError, SSCDeviceError


class FakeClient:
    """Client replacement: returns values from a dict, errors controllable."""

    def __init__(self, values: dict[tuple[str, ...], Any]) -> None:
        self.values = values
        self.fail_connection = False
        self.rejected_paths: set[tuple[str, ...]] = set()
        self.priority_waiting = asyncio.Event()

    async def get(self, path: tuple[str, ...], priority: bool = False) -> Any:
        if self.fail_connection:
            raise SSCConnectionError("device offline (test)")
        if path in self.rejected_paths:
            raise SSCDeviceError("path rejected (test)")
        return self.values.get(path)


@pytest.fixture
def fake_client() -> FakeClient:
    values: dict[tuple[str, ...], Any] = {
        PATH_OUTPUT_MUTE: False,  # fast path
        PATH_DEVICE_NAME: "Links",  # slow path
    }
    return FakeClient(values)


@pytest.fixture
def coordinator(hass, fake_client) -> NeumannKHCoordinator:
    coord = NeumannKHCoordinator(hass, fake_client, "test", model="KH 120 II")
    # No automatic re-scheduling in the test (prevents hanging timers).
    coord.update_interval = None
    return coord


def _value(coord: NeumannKHCoordinator, path: tuple[str, ...]) -> Any:
    return coord.value(path)


async def test_first_cycle_includes_slow_paths(coordinator, fake_client):
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_fast_cycle_serves_slow_values_from_cache(coordinator, fake_client):
    await coordinator.async_refresh()  # cycle 0: slow included
    # Device changes the slow value externally - the fast cycle must not
    # see it yet (only comes with the next slow poll).
    fake_client.values[PATH_DEVICE_NAME] = "Umbenannt"
    await coordinator.async_refresh()  # cycle 1: fast
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_confirmed_slow_value_survives_fast_cycle(coordinator, fake_client):
    """Regression v1.15.1: no snapping back after user action on a slow path."""
    await coordinator.async_refresh()  # cycle 0
    # User renames the device, device confirms.
    coordinator.apply_confirmed_value(PATH_DEVICE_NAME, "Neuer Name")
    fake_client.values[PATH_DEVICE_NAME] = "Neuer Name"  # device state
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"

    await coordinator.async_refresh()  # cycle 1: fast, mixes in cache
    # BEFORE the fix the value snapped back to "Links" here.
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"


async def test_confirmed_fast_value_not_cached_as_slow(coordinator, fake_client):
    """Counter-check: fast paths do not go through the slow cache."""
    await coordinator.async_refresh()
    coordinator.apply_confirmed_value(PATH_OUTPUT_MUTE, True)
    assert _value(coordinator, PATH_OUTPUT_MUTE) is True
    # Device meanwhile reports False again - the fresh poll value must win.
    fake_client.values[PATH_OUTPUT_MUTE] = False
    await coordinator.async_refresh()
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False


async def test_failed_slow_cycle_is_retried_next_cycle(coordinator, fake_client):
    """Pending flag: if the slow cycle fails, the next one catches it up."""
    fake_client.fail_connection = True
    await coordinator.async_refresh()  # cycle 0 (slow) fails
    assert not coordinator.last_update_success

    fake_client.fail_connection = False
    fake_client.values[PATH_DEVICE_NAME] = "Nach Reconnect"
    await coordinator.async_refresh()  # cycle 1: actually fast, catches up slow
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_DEVICE_NAME) == "Nach Reconnect"


async def test_slow_values_refresh_on_next_slow_cycle(coordinator, fake_client):
    from custom_components.neumann_kh.const import SLOW_POLL_EVERY_N_CYCLES

    await coordinator.async_refresh()  # cycle 0: slow
    fake_client.values[PATH_DEVICE_NAME] = "Changed later"
    for _ in range(SLOW_POLL_EVERY_N_CYCLES - 1):
        await coordinator.async_refresh()  # fast only
        assert _value(coordinator, PATH_DEVICE_NAME) == "Links"
    await coordinator.async_refresh()  # next slow cycle
    assert _value(coordinator, PATH_DEVICE_NAME) == "Changed later"


async def test_rejected_path_does_not_break_cycle(coordinator, fake_client):
    fake_client.rejected_paths.add(PATH_DEVICE_NAME)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False
    assert _value(coordinator, PATH_DEVICE_NAME) is None


async def test_all_slow_paths_registered_in_slow_set(coordinator):
    """Safeguard for the membership test of apply_confirmed_value()."""
    for path in SLOW_POLL_PATHS:
        assert path in coordinator._slow_path_set  # noqa: SLF001
