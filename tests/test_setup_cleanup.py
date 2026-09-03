"""What setup leaves behind when it is cancelled rather than failing.

`except Exception` does not catch `asyncio.CancelledError` - it derives from
BaseException so that a cancellation cannot be swallowed by accident. Both
cleanup handlers in `async_setup_entry` are written as `except Exception`, so
a setup cancelled while it waits - Home Assistant's setup timeout, a reload or
a removal during setup, a shutdown - walks past them: the socket stays open
and the connection stays open.

Measured against the hardware on 2026-09-02: a speaker answers two
simultaneous connections and the first survives the second, so a leaked socket
blocks nothing. That is why this is a cleanup test and not a bug report.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh.const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
)


@pytest.fixture
def _custom_integration(enable_custom_integrations, mock_async_zeroconf):
    yield


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KH 120 II Right",
        unique_id="SIM0001234",
        data={
            CONF_HOST: "fe80::2%2",
            CONF_PORT: 45,
            CONF_INTERFACE: "eth0",
            CONF_MODEL: "KH 120 II",
            CONF_SERIAL: "SIM0001234",
        },
    )
    entry.add_to_hass(hass)
    return entry


class _BlockingClient:
    """Answers nothing and records whether it was closed."""

    def __init__(self, **kwargs) -> None:
        self.closed = False
        self.reached_the_device = asyncio.Event()
        # The coordinator reads this one; the real client sets it while a user
        # action waits for the poll to yield.
        self.priority_waiting = asyncio.Event()

    async def get(self, path, priority: bool = False):
        self.reached_the_device.set()
        await asyncio.Event().wait()

    async def set(self, path, value, priority: bool = False):
        await asyncio.Event().wait()

    async def close(self) -> None:
        # Yields before recording, like the real client, which takes its lock
        # first. Without that a cancelled close would still look successful
        # here and the shield in the production code would go untested.
        await asyncio.sleep(0)
        self.closed = True


async def test_a_cancelled_setup_still_releases_the_connection(hass, _custom_integration):
    """Cancelling is not failing, and the cleanup only ran for failures.

    The cancellation is deliberate rather than timed: the fake reports when the
    setup is actually inside the first poll, so this cannot pass by cancelling
    before the connection was ever opened.
    """
    entry = _entry(hass)
    client = _BlockingClient()

    with patch("custom_components.neumann_kh.SSCClient", return_value=client):
        # Through Home Assistant, not by calling async_setup_entry directly:
        # the coordinator needs the config entry context HA sets around it,
        # and this is the path a real cancellation interrupts.
        setup = asyncio.get_running_loop().create_task(
            hass.config_entries.async_setup(entry.entry_id)
        )
        await asyncio.wait_for(client.reached_the_device.wait(), timeout=5)
        setup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await setup

    assert client.closed, "the connection was left open when the setup was cancelled"


class _AnsweringClient:
    """Answers everything, so setup gets past the first refresh."""

    def __init__(self, **kwargs) -> None:
        self.closed = False
        self.priority_waiting = asyncio.Event()

    async def get(self, path, priority: bool = False):
        return 0.0

    async def set(self, path, value, priority: bool = False):
        return None

    async def close(self) -> None:
        # Yields before recording, like the real client, which takes its lock
        # first. Without that a cancelled close would still look successful
        # here and the shield in the production code would go untested.
        await asyncio.sleep(0)
        self.closed = True


async def test_a_setup_cancelled_while_adding_platforms_cleans_up_too(hass, _custom_integration):
    """The sibling handler, one step further into the same function.

    Both cleanup blocks were written as `except Exception`; fixing only the
    one the first test covers would leave this one exactly as it was, and
    nothing would say so.
    """
    entry = _entry(hass)
    client = _AnsweringClient()
    adding_platforms = asyncio.Event()

    async def _never_finishes(config_entry, platforms):
        adding_platforms.set()
        await asyncio.Event().wait()

    with (
        patch("custom_components.neumann_kh.SSCClient", return_value=client),
        patch.object(hass.config_entries, "async_forward_entry_setups", _never_finishes),
    ):
        setup = asyncio.get_running_loop().create_task(
            hass.config_entries.async_setup(entry.entry_id)
        )
        await asyncio.wait_for(adding_platforms.wait(), timeout=5)
        setup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await setup

    assert client.closed, "the connection was left open when adding platforms was cancelled"
