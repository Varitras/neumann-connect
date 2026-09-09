"""A speaker that is switched off is not a fault.

Home Assistant's own quality-scale rule `log-when-unavailable` asks for
`info` level. DataUpdateCoordinator logs the first failed cycle at `error`
regardless (helpers/update_coordinator.py in 2026.9.0), so four monitors
switched off overnight write four red lines every day for the most ordinary
state there is.

A genuine fault - a cycle that runs over its time limit, a device that
answers but rejects everything - must stay `error`.
"""

from __future__ import annotations

import asyncio
import logging

from custom_components.neumann_kh import coordinator as coordinator_module
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.ssc_client import SSCConnectionError


class UnreachableClient:
    """Answers nothing at all - the speaker is switched off."""

    def __init__(self) -> None:
        self.priority_waiting = asyncio.Event()

    async def get(self, path: tuple[str, ...], priority: bool = False) -> object:
        raise SSCConnectionError("device offline (test)")


class SlowClient:
    """Answers, but too late for the cycle's time limit."""

    def __init__(self) -> None:
        self.priority_waiting = asyncio.Event()

    async def get(self, path: tuple[str, ...], priority: bool = False) -> object:
        await asyncio.sleep(0.2)
        return False


def _refresh_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.msg.startswith("Error fetching")]


async def test_a_switched_off_speaker_is_logged_as_info(hass, caplog):
    coordinator = NeumannKHCoordinator(hass, UnreachableClient(), "test", model="KH 120 II")
    coordinator.update_interval = None

    with caplog.at_level(logging.INFO):
        await coordinator.async_refresh()

    assert not coordinator.last_update_success
    records = _refresh_records(caplog)
    assert len(records) == 1, "the coordinator must still report the failed cycle once"
    assert records[0].levelno == logging.INFO


async def test_a_stalled_cycle_stays_an_error(hass, caplog, monkeypatch):
    monkeypatch.setattr(coordinator_module, "POLL_CYCLE_TIMEOUT_SECONDS", 0.01)
    coordinator = NeumannKHCoordinator(hass, SlowClient(), "test", model="KH 120 II")
    coordinator.update_interval = None

    with caplog.at_level(logging.INFO):
        await coordinator.async_refresh()

    assert not coordinator.last_update_success
    records = _refresh_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
