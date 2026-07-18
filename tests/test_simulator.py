"""Tests for the SSC device simulator (tools/ssc_simulator.py).

The simulator exists to exercise the integration without physical speakers, so
these tests drive it through the real SSCClient. Its value depends entirely on
reproducing the verified firmware restrictions - a permissive simulator would
hide real breakage. The rejection tests below are therefore the important ones.

Short timeouts (settle 0.05 s, timeout 0.3 s) keep the suite fast.
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
_TIMEOUT = 0.3


class SimulatorServer:
    """Runs an SSCSimulator on a loopback port for the duration of a test."""

    def __init__(self, model: str, enable_schema: bool = False) -> None:
        self.simulator = SSCSimulator(model, enable_schema=enable_schema)
        self.server: asyncio.Server | None = None
        self.port: int = 0

    async def start(self) -> None:
        async def connected(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
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
    """"dimm" does not exist on the KH 120 II -> the device reports 404."""
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
    """Container/collective queries are rejected by the firmware (400)."""
    client = _client(kh120.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.get(("device",))
    finally:
        await client.close()


async def test_schema_discovery_is_rejected(kh120):
    """osc/schema is optional and rejected unless explicitly enabled."""
    client = _client(kh120.port)
    try:
        with pytest.raises(SSCDeviceError):
            await client.request({"osc": {"schema": None}})
    finally:
        await client.close()


async def test_schema_discovery_works_when_enabled(socket_enabled):
    """With --enable-schema the optional osc methods actually answer.

    This is the only way to exercise the best-effort schema branch in
    discovery_export.py: real firmware rejects osc/schema, so without the
    simulator that code path is never executed anywhere.
    """
    srv = SimulatorServer(MODEL_KH_120_II, enable_schema=True)
    await srv.start()
    # The walk issues one request per node; the default settle time would add
    # seconds to the fast suite for no extra coverage.
    client = SSCClient(host="127.0.0.1", port=srv.port, timeout=_TIMEOUT, settle_time=0.005)
    try:
        schema = await client.request({"osc": {"schema": None}})
        level = schema["osc"]["schema"]
        # Containers are announced as {}, leaves as null.
        assert level["audio"] == {}
        assert level["warnings"] is None

        result = await async_discover_all_values(client)
        limits = result["schema_limits"]
        assert limits, "the schema walk produced nothing"
        # Writability must mirror the verified hardware behaviour.
        assert limits["audio"]["out"]["level"]["writeable"] is True
        assert limits["ui"]["input_gain"]["writeable"] is False
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
