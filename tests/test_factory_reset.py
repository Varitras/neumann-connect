"""Regression tests for the factory reset button.

The most destructive of the four actions had no test of its own: the
existing coverage went through the other two-click path, "restore backup".

The failure this file exists for: the reset command can reach the speaker
while the reply is lost to the reboot it triggers. The error path then ended
before the cache was dropped, so Home Assistant kept showing settings the
device no longer had - and every entity stayed wrong until a slow poll five
minutes later, or forever for values only written once.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh import button as button_module
from custom_components.neumann_kh.button import NeumannKHRestoreButton
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.ssc_client import SSCConnectionError, SSCDeviceError


class _Client:
    def __init__(self, raises: Exception | None = None) -> None:
        self.writes: list[tuple] = []
        self._raises = raises

    async def set(self, path: tuple[str, ...], value) -> None:
        self.writes.append(path)
        if self._raises is not None:
            raise self._raises


class _Coordinator:
    claim_device = NeumannKHCoordinator.claim_device

    def __init__(self, client: _Client) -> None:
        self.action_lock = asyncio.Lock()
        self.client = client
        self.invalidations = 0

    async def async_invalidate_and_refresh(self) -> None:
        self.invalidations += 1


def _armed_button(client: _Client, monkeypatch):
    """A reset button already past its first press."""
    monkeypatch.setattr(button_module, "async_dismiss_notification", lambda *a: None)
    monkeypatch.setattr(button_module, "async_create_notification", lambda *a, **k: None)
    return SimpleNamespace(
        coordinator=_Coordinator(client),
        hass=SimpleNamespace(config=SimpleNamespace(language="en")),
        _entry=SimpleNamespace(title="KH 120 II"),
        _armed_at=time.monotonic(),
        _notification_id="x",
    )


async def test_a_reset_whose_reply_is_lost_still_drops_the_cache(monkeypatch):
    """The command may have executed - the connection died, not the speaker.

    Treating a lost reply as "nothing happened" is the wrong way round for a
    reset: it is the one command that invalidates everything at once.
    """
    button = _armed_button(_Client(raises=SSCConnectionError("reset by peer")), monkeypatch)

    with pytest.raises(HomeAssistantError) as err:
        await NeumannKHRestoreButton.async_press(button)

    assert err.value.translation_key == "device_unreachable"
    assert button.coordinator.client.writes, "the reset was never sent"
    assert button.coordinator.invalidations == 1, (
        "a reset that may have run left the cached values in place"
    )


async def test_a_reset_the_device_refuses_leaves_the_cache_alone(monkeypatch):
    """Counter-check: an explicit rejection means nothing was written.

    Without it the fix above would be indistinguishable from "always
    invalidate", which would drop the cache on every mistyped path too.
    """
    button = _armed_button(_Client(raises=SSCDeviceError("405")), monkeypatch)

    with pytest.raises(HomeAssistantError) as err:
        await NeumannKHRestoreButton.async_press(button)

    assert err.value.translation_key == "factory_reset_rejected"
    assert button.coordinator.invalidations == 0


async def test_a_successful_reset_drops_the_cache(monkeypatch):
    button = _armed_button(_Client(), monkeypatch)

    await NeumannKHRestoreButton.async_press(button)

    assert button.coordinator.invalidations == 1
