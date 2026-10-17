"""Regression tests for the EQ reset button.

The audit of v1.18.1b4 found the reset to be the one device action outside
the action lock. A half-written reset (gain landed, boost rejected) must also
report the rejection. It needs no refresh: gain and boost are never polled, so
no cached value can be stale.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.eq import NeumannKHEQResetButton
from custom_components.neumann_kh.ssc_client import SSCDeviceError, SSCLocalModeError

_CONTAINER = SimpleNamespace(path=("audio", "out", "eq2"), band_count=2)


class _Client:
    """Records what was written; optionally rejects one leaf."""

    def __init__(self, reject: str | None = None, error: type = SSCDeviceError) -> None:
        self.written: list[str] = []
        self._reject = reject
        self._error = error

    async def set(self, path: tuple[str, ...], value) -> None:
        if path[-1] == self._reject:
            raise self._error("device rejected the write")
        self.written.append(path[-1])


class _Coordinator:
    """Enough of the coordinator for the press, with its REAL claim method."""

    claim_device = NeumannKHCoordinator.claim_device

    def __init__(self, client: _Client) -> None:
        self.action_lock = asyncio.Lock()
        self.client = client
        self.persisted = 0

    async def async_persist(self) -> None:
        self.persisted += 1


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


async def test_a_half_written_reset_reports_the_rejection():
    """gain landed, boost was rejected - the user must hear about it."""
    button = _button(_Client(reject="boost"))

    with pytest.raises(HomeAssistantError) as err:
        await NeumannKHEQResetButton.async_press(button)

    assert err.value.translation_key == "eq_reset_rejected"
    assert button.coordinator.client.written == ["gain"]


async def test_a_reset_in_local_mode_names_the_control_switch():
    button = _button(_Client(reject="gain", error=SSCLocalModeError))

    with pytest.raises(HomeAssistantError) as err:
        await NeumannKHEQResetButton.async_press(button)

    assert err.value.translation_key == "local_mode"


async def test_a_successful_reset_writes_both():
    button = _button(_Client())

    await NeumannKHEQResetButton.async_press(button)

    assert button.coordinator.client.written == ["gain", "boost"]


async def test_a_successful_reset_is_persisted():
    button = _button(_Client())
    await NeumannKHEQResetButton.async_press(button)
    assert button.coordinator.persisted == 1


async def test_a_rejected_reset_is_not_persisted():
    button = _button(_Client(reject="gain"))
    with pytest.raises(HomeAssistantError):
        await NeumannKHEQResetButton.async_press(button)
    assert button.coordinator.persisted == 0
