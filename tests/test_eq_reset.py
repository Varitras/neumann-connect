"""Regression tests for the EQ reset button.

Two failures the audit of v1.18.1b4 found, neither covered by any test: the
reset was the one device action outside the action lock, and a reset that
wrote gain and then failed on boost left the cached values untouched, so the
entities kept showing the old curve for a speaker that no longer has it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.eq import NeumannKHEQResetButton
from custom_components.neumann_kh.ssc_client import SSCDeviceError

_CONTAINER = SimpleNamespace(path=("audio", "out", "eq2"), band_count=2)


class _Client:
    """Records what was written; optionally rejects one leaf."""

    def __init__(self, reject: str | None = None) -> None:
        self.written: list[str] = []
        self._reject = reject

    async def set(self, path: tuple[str, ...], value) -> None:
        if path[-1] == self._reject:
            raise SSCDeviceError("device rejected the write")
        self.written.append(path[-1])


class _Coordinator:
    """Enough of the coordinator for the press, with its REAL claim method."""

    claim_device = NeumannKHCoordinator.claim_device

    def __init__(self, client: _Client) -> None:
        self.action_lock = asyncio.Lock()
        self.client = client
        self.refreshes = 0

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


def _button(client: _Client):
    return SimpleNamespace(coordinator=_Coordinator(client), _container=_CONTAINER)


async def test_a_reset_cannot_start_while_another_action_owns_the_device():
    """The reset was the fifth button and the only one outside the lock.

    A backup reading while the reset writes produces a snapshot that mixes the
    old curve with the new one and then replaces the last good backup.
    """
    button = _button(_Client())

    async with button.coordinator.claim_device():
        with pytest.raises(HomeAssistantError) as err:
            await NeumannKHEQResetButton.async_press(button)

    assert err.value.translation_key == "device_action_in_progress"
    assert button.coordinator.client.written == [], "wrote despite a busy device"


async def test_a_half_written_reset_still_refreshes():
    """gain landed, boost was rejected - the cache is stale either way."""
    button = _button(_Client(reject="boost"))

    with pytest.raises(HomeAssistantError):
        await NeumannKHEQResetButton.async_press(button)

    assert button.coordinator.client.written == ["gain"]
    assert button.coordinator.refreshes == 1, (
        "a reset that wrote half the container left the cached values alone"
    )


async def test_a_successful_reset_writes_both_and_refreshes():
    button = _button(_Client())

    await NeumannKHEQResetButton.async_press(button)

    assert button.coordinator.client.written == ["gain", "boost"]
    assert button.coordinator.refreshes == 1
