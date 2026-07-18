"""Tests for the SSC client against a real local asyncio TCP server.

Short timeouts (settle 0.05 s, timeout 0.3 s) to keep the suite fast -
the real production values (DEFAULT_QUERY_SETTLE, 3 s timeout) are
deliberately not used here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from custom_components.neumann_kh import ssc_client
from custom_components.neumann_kh.ssc_client import (
    SSCClient,
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
)

# The HA test plugin blocks sockets by default (no real network
# access in tests). These tests deliberately use a local TCP server
# on loopback - so sockets are explicitly enabled via the
# socket_enabled fixture (pytest-socket).

_SETTLE = 0.05
_TIMEOUT = 0.3


class FakeSSCServer:
    """Minimal SSC server: one handler per connection, responses controllable."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.port: int = 0
        self.connections: int = 0
        # Response factory: receives the parsed request, returns a list of
        # response objects (one per line). None entry = no response.
        self.responder = self.echo_responder
        self.response_delay: float = 0.0

    @staticmethod
    def echo_responder(request: dict) -> list[dict | None]:
        """Default: mirror the request back unchanged (like a get/set echo)."""
        return [request]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                request = json.loads(line)
                if self.response_delay:
                    await asyncio.sleep(self.response_delay)
                for response in self.responder(request):
                    if response is None:
                        continue
                    writer.write(json.dumps(response).encode() + b"\r\n")
                await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            # wait_closed() can hang under Python 3.12 for servers that never
            # accepted a connection - bound it hard.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), timeout=1)


@pytest.fixture
async def server(socket_enabled):
    srv = FakeSSCServer()
    await srv.start()
    yield srv
    await srv.stop()


def _client(port: int) -> SSCClient:
    return SSCClient(
        host="127.0.0.1", port=port, timeout=_TIMEOUT, settle_time=_SETTLE
    )


async def test_get_returns_value(server):
    server.responder = lambda req: [{"audio": {"out": {"mute": True}}}]
    client = _client(server.port)
    try:
        assert await client.get(("audio", "out", "mute")) is True
    finally:
        await client.close()


async def test_set_returns_confirmed_value(server):
    # Device confirms a different value than requested (e.g. clamping).
    server.responder = lambda req: [{"audio": {"out": {"level": -60}}}]
    client = _client(server.port)
    try:
        assert await client.set(("audio", "out", "level"), -80) == -60
    finally:
        await client.close()


async def test_answer_split_across_lines_is_merged(server):
    # While the requested path has not arrived yet, further lines are still
    # collected and merged - a firmware splitting its answer is handled.
    server.responder = lambda req: [
        {"audio": {"out": {"mute": False}}},
        {"device": {"name": "value"}},
    ]
    client = _client(server.port)
    try:
        assert await client.get(("device", "name")) == "value"
    finally:
        await client.close()


async def test_first_answer_for_the_path_ends_the_read(server):
    # Deliberate trade-off: the read returns as soon as the requested path is
    # present, so a later line for the SAME path no longer overrides it.
    # Measured against real hardware, a single leaf query is answered with
    # exactly one line, while waiting out the settle window cost 0.4 s per
    # path - 21.6 s of a 25 s cycle limit on a KH 750.
    server.responder = lambda req: [
        {"device": {"name": "first"}},
        {"device": {"name": "second"}},
    ]
    client = _client(server.port)
    try:
        assert await client.get(("device", "name")) == "first"
    finally:
        await client.close()


async def test_osc_error_raises_device_error(server):
    server.responder = lambda req: [
        {"osc": {"error": [400, {"desc": "message not understood"}]}}
    ]
    client = _client(server.port)
    try:
        with pytest.raises(SSCDeviceError, match="message not understood"):
            await client.get(("does", "not", "exist"))
    finally:
        await client.close()


async def test_invalid_json_line_is_ignored(socket_enabled):
    # An invalid line must not prevent the valid one that follows.
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"NOT JSON\r\n")
        writer.write(json.dumps({"device": {"name": "ok"}}).encode() + b"\r\n")
        await writer.drain()
        # Keep the connection open: after the last line the client still waits
        # the settle time, and a server close during that phase would
        # (correctly) be reported as a connection drop. Returning here would
        # close the writer, so hold the handler open past the settle time.
        await asyncio.sleep(0.5)

    raw_server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        assert await client.get(("device", "name")) == "ok"
    finally:
        await client.close()
        raw_server.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(raw_server.wait_closed(), timeout=1)


async def test_endless_talker_does_not_hold_the_read_open(socket_enabled, monkeypatch):
    # Every incoming line refreshes the settle window, so a device that never
    # stops talking would keep the read - and the client lock - busy forever.
    # The server below streams without pause and never sends the requested
    # path, so only the line cap can end this. Without it the test hangs.
    monkeypatch.setattr(ssc_client, "_MAX_RESPONSE_LINES", 20)

    async def _handle(reader, writer):
        await reader.readline()
        try:
            while True:
                writer.write(json.dumps({"other": {"value": 1}}).encode() + b"\r\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass

    raw_server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        assert await client.get(("device", "name")) is None
    finally:
        await client.close()
        raw_server.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(raw_server.wait_closed(), timeout=1)


async def test_timeout_raises_and_drops_connection(server):
    # Server does not respond at all -> SSCTimeoutError, connection dropped.
    server.responder = lambda req: [None]
    client = _client(server.port)
    try:
        with pytest.raises(SSCTimeoutError):
            await client.get(("device", "name"))
        assert client._writer is None  # noqa: SLF001 - deliberate whitebox test
    finally:
        await client.close()


async def test_connection_refused_raises_connection_error(socket_enabled):
    # Port without a server.
    client = SSCClient(host="127.0.0.1", port=1, timeout=_TIMEOUT, settle_time=_SETTLE)
    with pytest.raises(SSCConnectionError):
        await client.get(("device", "name"))


async def test_cancelled_request_drops_connection_no_stale_bleed(server):
    """Hardening regression: cancellation drops the connection.

    The delayed response of the cancelled request must not be assigned to
    the next request (v1.15.0 hardening).
    """
    server.response_delay = 0.2  # response arrives only after the cancellation
    server.responder = lambda req: [{"stale": {"value": 1}}]
    client = _client(server.port)
    try:
        task = asyncio.create_task(client.get(("stale", "value")))
        await asyncio.sleep(0.05)  # request is out, response not yet here
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Connection must have been dropped.
        assert client._writer is None  # noqa: SLF001

        # Follow-up request: gets a NEW connection and the correct response.
        server.response_delay = 0.0
        server.responder = lambda req: [{"fresh": {"value": 2}}]
        assert await client.get(("fresh", "value")) == 2
        assert server.connections == 2
    finally:
        await client.close()


async def test_oversized_line_raises_connection_error(socket_enabled):
    # Line above the StreamReader limit (1 MiB) without a terminator.
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"x" * (1_100_000))  # no \n
        await writer.drain()
        writer.close()

    raw_server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        with pytest.raises(SSCConnectionError):
            await client.get(("device", "name"))
    finally:
        await client.close()
        raw_server.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(raw_server.wait_closed(), timeout=1)


def test_is_link_local():
    assert SSCClient._is_link_local("fe80::1")  # noqa: SLF001
    assert SSCClient._is_link_local("FE80::1")  # noqa: SLF001
    assert SSCClient._is_link_local("febf::1")  # noqa: SLF001
    assert not SSCClient._is_link_local("fec0::1")  # noqa: SLF001
    assert not SSCClient._is_link_local("2001:db8::1")  # noqa: SLF001
    assert not SSCClient._is_link_local("127.0.0.1")  # noqa: SLF001


def test_connect_host_appends_scope_for_link_local():
    client = SSCClient(host="fe80::1", port=45, interface="eth0")
    assert client._connect_host == "fe80::1%eth0"  # noqa: SLF001
    client2 = SSCClient(host="2001:db8::1", port=45, interface="eth0")
    assert client2._connect_host == "2001:db8::1"  # noqa: SLF001
