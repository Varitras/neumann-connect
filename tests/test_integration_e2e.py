"""End-to-end test: the real integration against the device simulator.

Unlike test_coordinator.py (fake client) and test_simulator.py (simulator
only), this drives the actual Home Assistant setup path: config entry ->
async_setup_entry -> SSCClient -> coordinator -> platform entities. It is the
closest automated equivalent to clicking the integration together in the UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh import storage
from custom_components.neumann_kh.const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
)
from custom_components.neumann_kh.export_file import EXPORT_DIR_NAME
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


async def _enable(hass, entry, suffix: str) -> None:
    """Enable an entity that is disabled by default, and reload for it.

    The destructive buttons (factory reset, restore) are hidden by default.
    Pressing a disabled entity silently does nothing, so this has to happen
    once up front - and only once, because the reload builds new entity
    instances and would discard a pending two-click confirmation.
    """
    registry = er.async_get(hass)
    entity = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.entity_id.endswith(suffix)
    )
    registry.async_update_entity(entity.entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def _press(hass, entry, suffix: str) -> None:
    """Press the button of this entry whose unique id ends with `suffix`."""
    entity_id = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.entity_id.endswith(suffix)
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


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


async def test_no_update_listener_is_registered(hass, socket_enabled):
    """An update listener next to async_update_reload_and_abort() is deprecated.

    Home Assistant reports the combination since 2026.6 and turns it into an
    error in 2026.12; it also causes double reloads today. The reconfigure flow
    reloads by itself, so no listener may come back.
    """
    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        assert not entry.update_listeners


async def test_backup_button_writes_a_file_outside_www(hass, socket_enabled, tmp_path):
    """The user path: press the button, get a file in the non-public folder."""
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _press(hass, entry, "_create_backup")

        written = list((tmp_path / EXPORT_DIR_NAME).glob("*.json"))
        assert written, "no export file was written"
        # Never in www/: Home Assistant serves that folder unauthenticated.
        assert not (tmp_path / "www").exists()

        payload = json.loads(written[0].read_text(encoding="utf-8"))
        assert payload["values"], "the export carries no values"
        assert payload["serial"] == "xxxxxxx234", "the real serial must not be exported"
        # The full EQ has to be in there, not just the switchable part.
        eq = payload["values"]["audio"]["out"]["eq2"]
        assert set(eq) >= {"enabled", "gain", "boost", "frequency", "q", "type"}


async def test_restore_needs_two_presses_and_writes_back(hass, socket_enabled, tmp_path):
    """Restore is destructive, so the first press only arms it."""
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _press(hass, entry, "_create_backup")

        # Change something so a restore has visible work to do.
        mute = next(
            e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
            if e.entity_id.startswith("switch.") and e.entity_id.endswith("_mute")
        )
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": mute}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(mute).state == "on"

        await _enable(hass, entry, "_restore_backup")
        await _press(hass, entry, "_restore_backup")  # arms only
        assert hass.states.get(mute).state == "on", "first press must not write"

        await _press(hass, entry, "_restore_backup")  # confirms
        await hass.async_block_till_done()
        assert hass.states.get(mute).state == "off", "restore did not write the backup back"


async def test_restore_refreshes_slow_polled_values_too(hass, socket_enabled, tmp_path):
    """A restored value must show up in the UI, not just reach the device.

    The device name is a slow-poll path, fetched only every tenth cycle. A
    plain refresh after a restore therefore re-merges the cached pre-restore
    value, and the entity keeps showing the old name for up to five minutes -
    which looks exactly like "the restore did not work".
    """
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        # Both are hidden by default; enable them before any press, because
        # the reload inside _enable would discard a pending confirmation.
        await _enable(hass, entry, "_device_name")
        await _enable(hass, entry, "_restore_backup")

        name_entity = next(
            e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
            if e.entity_id.startswith("text.")
        )
        original = hass.states.get(name_entity).state
        assert original and original != "unknown"

        await _press(hass, entry, "_create_backup")

        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": name_entity, "value": "Changed"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert hass.states.get(name_entity).state == "Changed"

        await _press(hass, entry, "_restore_backup")
        await _press(hass, entry, "_restore_backup")
        await hass.async_block_till_done()

        assert hass.states.get(name_entity).state == original, (
            "the restored name never reached the entity"
        )


async def test_restore_updates_entities_once(hass, socket_enabled, tmp_path):
    """One coordinator update for the whole restore, not one per value.

    Each update copies the data tree and notifies every entity of the device,
    so per-path updates produced thousands of state changes - and rows in the
    recorder - for a single button press.
    """
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _press(hass, entry, "_create_backup")
        await _enable(hass, entry, "_restore_backup")

        coordinator = hass.data[DOMAIN][entry.entry_id]
        updates = 0
        original = coordinator.async_set_updated_data

        def counting(data):
            nonlocal updates
            updates += 1
            return original(data)

        coordinator.async_set_updated_data = counting

        await _press(hass, entry, "_restore_backup")
        await _press(hass, entry, "_restore_backup")
        await hass.async_block_till_done()

        assert updates == 1, f"restore pushed {updates} updates instead of one"


async def test_restore_writes_what_was_confirmed(hass, socket_enabled, tmp_path):
    """A backup created between the two presses must not be restored instead.

    The confirmation shows one snapshot's timestamp; silently applying another
    would make the two-press confirmation meaningless.
    """
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _enable(hass, entry, "_device_name")
        await _enable(hass, entry, "_restore_backup")

        name_entity = next(
            e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
            if e.entity_id.startswith("text.")
        )
        original_name = hass.states.get(name_entity).state

        await _press(hass, entry, "_create_backup")  # snapshot A
        await _press(hass, entry, "_restore_backup")  # arms on A

        # Change something, then take snapshot B before confirming.
        await hass.services.async_call(
            "text", "set_value", {"entity_id": name_entity, "value": "B"}, blocking=True
        )
        await hass.async_block_till_done()
        await _press(hass, entry, "_create_backup")  # snapshot B

        await _press(hass, entry, "_restore_backup")  # confirms - must apply A
        await hass.async_block_till_done()

        assert hass.states.get(name_entity).state == original_name, (
            "the restore applied a newer backup than the one confirmed"
        )


async def test_restore_leaves_command_paths_alone(hass, socket_enabled, tmp_path):
    """The factory reset path must never be written by a restore."""
    hass.config.config_dir = str(tmp_path)

    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _press(hass, entry, "_create_backup")
        await _enable(hass, entry, "_restore_backup")

        coordinator = hass.data[DOMAIN][entry.entry_id]
        written_paths = []
        original_set = coordinator.client.set

        async def recording(path, value, **kwargs):
            written_paths.append(path)
            return await original_set(path, value, **kwargs)

        coordinator.client.set = recording

        await _press(hass, entry, "_restore_backup")
        await _press(hass, entry, "_restore_backup")
        await hass.async_block_till_done()

        assert written_paths, "the restore wrote nothing at all"
        for forbidden in (("device", "restore"), ("device", "save_settings"),
                          ("device", "identification", "visual")):
            assert forbidden not in written_paths, f"restore wrote {forbidden}"


async def test_restore_without_a_backup_refuses(hass, socket_enabled, tmp_path):
    hass.config.config_dir = str(tmp_path)
    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _enable(hass, entry, "_restore_backup")
        with pytest.raises(HomeAssistantError, match="backup"):
            await _press(hass, entry, "_restore_backup")


async def test_restore_refuses_a_backup_from_another_model(hass, socket_enabled, tmp_path):
    """Writing a KH 750's settings into a KH 120 II must not happen."""
    hass.config.config_dir = str(tmp_path)
    async with _simulator(MODEL_KH_120_II) as port:
        entry = await _setup_entry(hass, MODEL_KH_120_II, port, "SIM0001234")
        await _press(hass, entry, "_create_backup")

        stored = await storage.async_get_backup(hass, "SIM0001234")
        stored["model"] = MODEL_KH_750
        await storage.async_save_backup(hass, "SIM0001234", stored)

        await _enable(hass, entry, "_restore_backup")
        with pytest.raises(HomeAssistantError, match="KH 750"):
            await _press(hass, entry, "_restore_backup")


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

