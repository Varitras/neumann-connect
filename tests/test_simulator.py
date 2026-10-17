"""Tests for the SSC device simulator (tools/ssc_simulator.py).

The simulator exists to exercise the integration without physical speakers, so
these tests drive it through the real SSCClient. Its value depends entirely on
reproducing the verified firmware restrictions - a permissive simulator would
hide real breakage. The rejection tests below are therefore the important ones.

A short settle window (0.05 s) keeps the suite fast; the connection
timeout is deliberately generous, see below.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from custom_components.neumann_kh.discovery_export import async_discover_all_values
from custom_components.neumann_kh.ssc_client import SSCClient, SSCDeviceError
from tools.ssc_simulator import (
    MODEL_KH_120_II,
    MODEL_KH_750,
    SSCSimulator,
    _handle_client,
)

# The HA test plugin blocks sockets; these tests use a real local TCP server
# and therefore need the socket_enabled fixture (the allow_hosts marker does
# NOT work for this).

_SETTLE = 0.05
# Not 0.3: on a loaded machine even a loopback connection needs longer than
# that, and the client then reports a timeout that has nothing to do with the
# simulator. test_ssc_client.py hit exactly this and was raised to 2.0; this
# file kept the tight value and started failing intermittently in the full run.
_TIMEOUT = 2.0


class SimulatorServer:
    """Runs an SSCSimulator on a loopback port for the duration of a test."""

    def __init__(self, model: str, enable_schema: bool = True) -> None:
        self.simulator = SSCSimulator(model, enable_schema=enable_schema)
        self.server: asyncio.Server | None = None
        self.port: int = 0

    async def start(self) -> None:
        async def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await _handle_client(self.simulator, reader, writer)

        # IPv4 loopback on purpose: the HA test plugin allows only 127.0.0.1
        # (socket_allow_hosts), so binding ::1 fails on Linux and in CI. The
        # simulator and the client are address-family agnostic.
        self.server = await asyncio.start_server(connected, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            # wait_closed() can hang under Python 3.12 for servers that never
            # accepted a connection - bound it hard.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), timeout=1)


@pytest.fixture
async def kh120(socket_enabled):
    srv = SimulatorServer(MODEL_KH_120_II)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.fixture
async def kh750(socket_enabled):
    srv = SimulatorServer(MODEL_KH_750)
    await srv.start()
    yield srv
    await srv.stop()


def _client(port: int) -> SSCClient:
    return SSCClient(host="127.0.0.1", port=port, timeout=_TIMEOUT, settle_time=_SETTLE)


async def test_get_and_set_roundtrip(kh120):
    """A writable value can be read, written and read back."""
    client = _client(kh120.port)
    try:
        assert await client.get(("device", "identity", "product")) == MODEL_KH_120_II
        # The config flow uses the vendor to spot devices of other makers.
        assert await client.get(("device", "identity", "vendor")) == "Georg Neumann GmbH"
        assert await client.get(("audio", "out", "level")) == 100.0
        assert await client.set(("audio", "out", "level"), 85.5) == 85.5
        assert await client.get(("audio", "out", "level")) == 85.5
    finally:
        await client.close()


async def test_missing_path_is_rejected(kh120):
    """ "dimm" exists on neither test model -> the device reports 404."""
    client = _client(kh120.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.get(("audio", "out", "dimm"))
    finally:
        await client.close()


async def test_read_only_path_rejects_set(kh120):
    """Fields confirmed read-only on real hardware must reject a set (405)."""
    client = _client(kh120.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.set(("ui", "input_gain"), "3 dB")
    finally:
        await client.close()


async def test_container_query_is_rejected(kh120):
    """A container query is answered with a 404 at the container (recorded)."""
    client = _client(kh120.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.get(("device",))
    finally:
        await client.close()


async def test_firmware_without_introspection_can_be_simulated(socket_enabled):
    """osc/schema is optional; --disable-schema stands in for firmware without it."""
    srv = SimulatorServer(MODEL_KH_120_II, enable_schema=False)
    await srv.start()
    client = _client(srv.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.request({"osc": {"schema": None}})
    finally:
        await client.close()
        await srv.stop()


async def test_the_schema_walk_covers_the_whole_tree_at_the_real_settle_time(socket_enabled):
    """Both tested firmwares answer osc/schema and osc/limits.

    At the client's default settle time on purpose: a walk that waits it out
    after every reply ran into its 30 s limit on a real KH 750, and the
    shortened settle time this test used to set hid exactly that.
    """
    srv = SimulatorServer(MODEL_KH_120_II)
    await srv.start()
    client = SSCClient(host="127.0.0.1", port=srv.port, timeout=_TIMEOUT)
    try:
        result = await async_discover_all_values(client)
        limits = result["schema_limits"]
        # Every leaf of the device state came back with its description.
        for path in _leaf_paths(srv.simulator.state):
            node = limits
            for key in path:
                node = node[key]
            assert node[0]["type"] in ("Number", "String", "Boolean"), path
    finally:
        await client.close()
        await srv.stop()


async def test_subwoofer_model_reports_kh_750(kh750):
    """The KH 750 reports itself without the "DSP" suffix and has out1/out2."""
    client = _client(kh750.port)
    try:
        assert await client.get(("device", "identity", "product")) == MODEL_KH_750
        assert await client.get(("audio", "out1", "level")) == 100.0
        # Bass management is confirmed not writable on the KH 750.
        with pytest.raises(SSCDeviceError):
            await client.set(("ui", "bass_management"), "2.1")
    finally:
        await client.close()


async def test_auto_standby_is_writable_on_a_monitor(kh120):
    """The split the entities rely on: switch here, binary sensor on the sub."""
    client = _client(kh120.port)
    try:
        assert await client.set(("device", "standby", "enabled"), False) is False
    finally:
        await client.close()


async def test_auto_standby_is_read_only_on_the_subwoofer(kh750):
    """Hardware answers 405 here, so the simulator has to as well.

    Accepting it would let a test pass against the simulator that real
    hardware refuses - the restore allowlist depends on exactly this split.
    """
    client = _client(kh750.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.set(("device", "standby", "enabled"), False)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "path",
    [
        ("audio", "out1", "loudspeaker"),
        ("audio", "out2", "loudspeaker"),
    ],
)
async def test_output_loudspeaker_is_read_only(kh750, path):
    """Modelled as sensors, so the simulator has to refuse a write.

    Accepting it would let a test pass here that real hardware answers with a
    405, which is exactly what the simulator exists to prevent.
    """
    client = _client(kh750.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.set(path, "KH 120 II")
    finally:
        await client.close()


def test_the_out5_variant_moves_only_level_and_mute():
    """Firmware 1.2.x layout: level and mute live in audio/out5, delay stays."""
    simulator = SSCSimulator(MODEL_KH_750, output_on_out5=True)

    assert simulator.handle({"audio": {"out": {"level": None}}}) == {
        "osc": {"error": [{"audio": {"out": {"level": [404, {"desc": "address not found"}]}}}]}
    }
    assert simulator.handle({"audio": {"out5": {"level": None}}}) == {
        "audio": {"out5": {"level": 100.0}}
    }
    assert "osc" not in simulator.handle({"audio": {"out": {"delay": None}}})
    assert simulator.handle({"device": {"identity": {"version": None}}}) == {
        "device": {"identity": {"version": "1_2_4"}}
    }


def _leaf_paths(tree, prefix=()):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _leaf_paths(value, prefix + (key,))
        else:
            yield prefix + (key,)
