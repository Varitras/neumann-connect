"""End-to-end test: the real integration against the device simulator.

Unlike test_coordinator.py (fake client) and test_simulator.py (simulator
only), this drives the actual Home Assistant setup path: config entry ->
async_setup_entry -> SSCClient -> coordinator -> platform entities. It is the
closest automated equivalent to clicking the integration together in the UI.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh.const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
)
from tools.ssc_simulator import MODEL_KH_120_II, MODEL_KH_750, SSCSimulator, _handle_client

# Deselected by default (see pytest.ini) because each test boots a full Home
# Assistant instance. The global 30 s hang guard is too tight for that - the
# KH 750 setup alone takes ~24 s.
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(120),
]


@pytest.fixture(autouse=True)
def _integration_env(enable_custom_integrations, mock_async_zeroconf):
    """Make the integration loadable and keep zeroconf out of the test.

    enable_custom_integrations: Home Assistant only loads custom_components in
    tests when asked to. Scoped to this module - the other test files drive the
    coordinator and simulator directly and do not need it.

    mock_async_zeroconf: the manifest declares a zeroconf dependency, so setting
    up an entry would start real mDNS discovery, open discovery flows for
    unrelated integrations (matter, cast, ...) and fail at teardown because
    their packages are not installed here.
    """
    yield


@contextlib.asynccontextmanager
async def _simulator(model: str):
    """Run a simulator on an ephemeral loopback port for the test."""
    simulator = SSCSimulator(model)

    async def connected(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await _handle_client(simulator, reader, writer)

    # IPv4: the HA test plugin only allows 127.0.0.1 (socket_allow_hosts).
    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(server.wait_closed(), timeout=1)


async def _setup_entry(hass, model: str, port: int, serial: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Simulated {model}",
        unique_id=serial,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_INTERFACE: "",
            CONF_MODEL: model,
            CONF_SERIAL: serial,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize(
    ("model", "serial"),
    [(MODEL_KH_120_II, "SIM0001234"), (MODEL_KH_750, "SIM0007500")],
)
async def test_integration_creates_entities(hass, socket_enabled, model, serial):
    """The integration sets up and produces entities fed by the simulator."""
    async with _simulator(model) as port:
        entry = await _setup_entry(hass, model, port, serial)

        # Scope every assertion to THIS config entry. Checking hass.states
        # globally would pass on unrelated Home Assistant states and turn this
        # into a test that cannot fail.
        assert entry.state is ConfigEntryState.LOADED

        registry = er.async_get(hass)
        registered = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert registered, "the config entry registered no entities"

        states = [
            state
            for state in (hass.states.get(e.entity_id) for e in registered)
            if state is not None
        ]
        assert states, "entities were registered but none reached the state machine"

        # Values must come from the simulator, not be unknown across the board.
        known = [s for s in states if s.state not in ("unknown", "unavailable")]
        assert known, "every entity stayed unknown - polling did not work"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_writing_a_value_reaches_the_device(hass, socket_enabled):
    """A user action is written through and confirmed by the device."""
    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")

        registry = er.async_get(hass)
        mute = next(
            (
                e.entity_id
                for e in er.async_entries_for_config_entry(registry, entry.entry_id)
                if e.entity_id.startswith("switch.") and e.entity_id.endswith("_mute")
            ),
            None,
        )
        assert mute, "mute switch entity not found for this config entry"

        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": mute}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(mute).state == "on"

