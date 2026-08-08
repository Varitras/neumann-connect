"""Tests for the SSC client against a real local asyncio TCP server.

Short timeouts (settle 0.05 s, timeout 0.3 s) to keep the suite fast -
the real production values (DEFAULT_QUERY_SETTLE, 3 s timeout) are
deliberately not used here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import struct

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
# Generous on purpose. This has to cover a loopback connect on a *loaded*
# machine, not just an idle one: at 0.3 s the whole suite failed roughly once
# in eight full runs, always in whichever test happened to be connecting when
# the machine stalled - which is why it never reproduced in isolation and took
# three sightings to pin down. Production uses 3.0 s.
_TIMEOUT = 2.0
# Only where the timeout itself is what is being tested.
_SHORT_TIMEOUT = 0.3
# Comfortably past the client's stale-drain window, so a line written after
# this gap is one the drain can no longer catch.
_STALE_DRAIN_GAP = 0.05


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
        # Deterministic alternative to response_delay: set `release` to an
        # Event and the handler holds the answer back until the test sets it.
        # `request_received` fires once a request has been parsed. Together
        # they let a test order "request is out" against "answer arrives"
        # without betting on a sleep being longer than the scheduler's mood -
        # a bet that lost roughly every third full run under E2E load.
        self.request_received = asyncio.Event()
        self.release: asyncio.Event | None = None

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
                self.request_received.set()
                if self.release is not None:
                    await self.release.wait()
                elif self.response_delay:
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


async def _serve(handler):
    """Start a bare server and keep track of its connection handlers.

    Handlers in this file deliberately stay alive after answering: closing the
    writer would make the client see EOF during the settle window and report a
    dropped connection instead of reading the answer. That also means a handler
    is still running when the test body ends, so its task has to be cancelled
    explicitly - otherwise the Home Assistant test harness fails the teardown
    with "lingering task". That only ever surfaced on the slower CI machine,
    which is why it belongs in one helper rather than in whichever test
    happened to trip over it.
    """
    tasks: set[asyncio.Task] = set()

    async def _tracked(reader, writer):
        task = asyncio.current_task()
        if task is not None:
            tasks.add(task)
        try:
            await handler(reader, writer)
        finally:
            writer.close()

    server = await asyncio.start_server(_tracked, "127.0.0.1", 0)
    return server, tasks


async def _shutdown(server, tasks) -> None:
    """Cancel every handler, then close the server."""
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    server.close()
    # wait_closed() can hang for a server that never accepted a connection -
    # bound it hard.
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(server.wait_closed(), timeout=1)


async def _stay_open() -> None:
    """Hold a handler open until the test tears the server down.

    A fixed sleep raced the test from both ends: too short and the client sees
    EOF mid-read, too long and the task outlives the test body.
    """
    await asyncio.Event().wait()


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
        await _stay_open()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        assert await client.get(("device", "name")) == "ok"
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_endless_talker_does_not_hold_the_read_open(socket_enabled, monkeypatch):
    # Every incoming line refreshes the settle window, so a device that never
    # stops talking would keep the read - and the client lock - busy forever.
    # The server below streams without pause and never sends the requested
    # path, so only the line cap can end this. Without it the test hangs.
    monkeypatch.setattr(ssc_client, "_MAX_RESPONSE_LINES", 20)

    async def _handle(reader, writer):
        await reader.readline()
        # More than the cap, queued in one go. Pacing the lines would race the
        # settle window: on a loaded machine the read ends normally before the
        # cap is reached, and the test then fails for a reason that has
        # nothing to do with the limit.
        for _ in range(100):
            writer.write(json.dumps({"other": {"value": 1}}).encode() + b"\r\n")
        await writer.drain()
        # Keep talking afterwards, which is the scenario being guarded against.
        try:
            while True:
                writer.write(json.dumps({"other": {"value": 1}}).encode() + b"\r\n")
                await writer.drain()
                await asyncio.sleep(0.001)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = SSCClient(host="127.0.0.1", port=port, timeout=5.0, settle_time=_SETTLE)
    try:
        assert await client.get(("device", "name")) is None
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_timeout_raises_and_drops_connection(server):
    # Server does not respond at all -> SSCTimeoutError, connection dropped.
    # Short timeout here so the test does not sit out the generous default.
    server.responder = lambda req: [None]
    client = SSCClient(
        host="127.0.0.1", port=server.port, timeout=_SHORT_TIMEOUT, settle_time=_SETTLE
    )
    try:
        with pytest.raises(SSCTimeoutError):
            await client.get(("device", "name"))
        assert client._writer is None
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
    # The answer is held back by an Event, not by a delay, so "request is out
    # but unanswered" holds no matter how loaded the machine is.
    server.release = asyncio.Event()
    server.responder = lambda req: [{"stale": {"value": 1}}]
    client = _client(server.port)
    try:
        task = asyncio.create_task(client.get(("stale", "value")))
        await asyncio.wait_for(server.request_received.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Connection must have been dropped.
        assert client._writer is None

        # Let the stale answer out now - it must not reach the next request.
        server.release.set()
        server.release = None

        # Follow-up request: gets a NEW connection and the correct response.
        server.responder = lambda req: [{"fresh": {"value": 2}}]
        assert await client.get(("fresh", "value")) == 2

        assert server.connections == 2
    finally:
        await client.close()


async def test_cancellation_in_the_drain_window_drops_the_connection(server, monkeypatch):
    """Cancellation before the request goes out must drop the connection too.

    Connecting and draining both await, so a cancellation can land there.
    While that window sat outside the try block, _drop_connection() was
    skipped and the client kept a socket the caller believed was gone -
    the invariant the v1.15.0 hardening rests on held only from _send_raw
    onwards. Found because the sibling test above hit this window roughly
    once in seven full runs on a cold machine.
    """
    in_drain = asyncio.Event()

    async def _hanging_drain(self) -> None:
        in_drain.set()
        await asyncio.sleep(60)  # hold the request inside the drain window

    monkeypatch.setattr(SSCClient, "_discard_stale_lines", _hanging_drain)

    client = _client(server.port)
    try:
        task = asyncio.create_task(client.get(("device", "name")))
        await asyncio.wait_for(in_drain.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert client._writer is None, (
            "cancellation during the drain window kept the connection"
        )
    finally:
        await client.close()


async def test_oversized_line_raises_connection_error(socket_enabled):
    # Line above the StreamReader limit (1 MiB) without a terminator.
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"x" * (1_100_000))  # no \n
        await writer.drain()
        writer.close()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        with pytest.raises(SSCConnectionError):
            await client.get(("device", "name"))
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_connection_is_dropped_after_a_safety_limit(socket_enabled, monkeypatch):
    """Hitting a limit must poison the connection, not just stop reading.

    Lines already queued on the socket would otherwise be handed to the next
    request, which would then read the previous request's answer.
    """
    monkeypatch.setattr(ssc_client, "_MAX_RESPONSE_LINES", 5)

    async def _handle(reader, writer):
        await reader.readline()
        # Everything up front rather than paced: a server that sleeps between
        # lines races the settle window, and on a loaded machine the read ends
        # normally before the cap is ever reached - so the assertion below
        # would fail for a reason that has nothing to do with the limit.
        for _ in range(50):
            writer.write(json.dumps({"other": {"value": 1}}).encode() + b"\r\n")
        await writer.drain()
        await _stay_open()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = SSCClient(host="127.0.0.1", port=port, timeout=5.0, settle_time=_SETTLE)
    try:
        await client.get(("device", "name"))
        assert client._writer is None, "the connection survived a safety limit"
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_write_failure_becomes_a_connection_error(server):
    """A peer that vanishes between connect and write must not look like a timeout."""
    client = _client(server.port)
    try:
        await client.get(("device", "name"))  # establishes the connection

        class _DeadWriter:
            def write(self, _data):
                raise BrokenPipeError("peer went away")

            def is_closing(self):
                return False

            def close(self):
                pass

        client._writer = _DeadWriter()
        with pytest.raises(SSCConnectionError):
            await client.get(("device", "name"))
    finally:
        client._writer = None
        await client.close()


async def test_leftover_line_is_not_read_as_the_next_answer(server):
    """The early return can leave lines buffered; they must not bleed over.

    A read returns as soon as the requested path arrives, so a second line for
    the same answer stays on the socket. Without draining it, the next request
    would read it as its own reply and every following answer would be off by
    one.
    """
    server.responder = lambda req: [
        {"device": {"name": "first"}},
        {"device": {"name": "leftover"}},
    ]
    client = _client(server.port)
    try:
        assert await client.get(("device", "name")) == "first"

        # Ask for the SAME path again. This is the case that actually bites: a
        # leftover line for a different path would just be merged harmlessly,
        # but one for the requested path satisfies the read immediately and is
        # returned as the fresh answer.
        server.responder = lambda req: [{"device": {"name": "fresh"}}]
        assert await client.get(("device", "name")) == "fresh"
        assert server.connections == 1, "the fix must not cost a reconnect"
    finally:
        await client.close()


async def test_cancelled_priority_request_does_not_wedge_the_poll_loop(server):
    """A cancelled priority request must not leave the event set.

    The poll loop sleeps before every single path while priority_waiting is
    set, so a stuck event slows down every cycle until another priority
    request happens to complete.
    """
    server.release = asyncio.Event()
    client = _client(server.port)
    try:
        # Occupy the lock so the priority request has to wait for it: the
        # blocker holds it until the server is released.
        blocker = asyncio.create_task(client.get(("device", "name")))
        await asyncio.wait_for(server.request_received.wait(), timeout=5)

        waiter = asyncio.create_task(client.set(("audio", "out", "mute"), True))
        # request() sets the flag before it queues on the lock, so waiting for
        # the event is exactly the state this test needs - no sleep required.
        await asyncio.wait_for(client.priority_waiting.wait(), timeout=5)

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        server.release.set()
        server.release = None
        with contextlib.suppress(Exception):
            await blocker

        assert not client.priority_waiting.is_set(), "event stayed set after cancellation"
    finally:
        await client.close()


def test_is_link_local():
    assert SSCClient.is_link_local("fe80::1")
    assert SSCClient.is_link_local("FE80::1")
    assert SSCClient.is_link_local("febf::1")
    assert not SSCClient.is_link_local("fec0::1")
    assert not SSCClient.is_link_local("2001:db8::1")
    assert not SSCClient.is_link_local("127.0.0.1")


def test_connect_host_appends_scope_for_link_local():
    client = SSCClient(host="fe80::1", port=45, interface="eth0")
    assert client._connect_host == "fe80::1%eth0"
    client2 = SSCClient(host="2001:db8::1", port=45, interface="eth0")
    assert client2._connect_host == "2001:db8::1"


async def test_stale_drain_gives_up_instead_of_stalling_a_request(
    socket_enabled, monkeypatch
):
    """An endpoint talking inside the drain window must not block the request.

    Only the per-line wait was short, so an endpoint producing complete lines
    faster than that could hold the drain loop and the request would never be
    written. A poll cycle has its own time limit; a button press does not.

    Driven by the line cap rather than the clock: the server queues everything
    up front, so the drain meets a full buffer with no timing to race.
    """
    monkeypatch.setattr(ssc_client, "_MAX_STALE_DRAIN_LINES", 5)

    async def _handle(reader, writer):
        await reader.readline()
        # The answer, followed by more than the drain is willing to discard.
        writer.write(json.dumps({"device": {"name": "first"}}).encode() + b"\r\n")
        for _ in range(50):
            writer.write(json.dumps({"noise": {"value": 1}}).encode() + b"\r\n")
        await writer.drain()
        await _stay_open()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        assert await client.get(("device", "name")) == "first"

        # Second request: the drain hits its cap and drops the connection
        # rather than reading on forever.
        with pytest.raises(SSCConnectionError):
            await asyncio.wait_for(client.get(("device", "name")), timeout=5)
        assert client._writer is None
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_a_response_is_bounded_by_total_size(socket_enabled, monkeypatch, caplog):
    """The line count alone bounds nothing useful.

    256 lines of the maximum size would be a quarter of a gigabyte held in
    memory, which matters on the machines Home Assistant usually runs on.
    """
    # Leave the line cap at its default: the point is that the size limit
    # fires FIRST, so asserting "connection dropped" alone would pass either
    # way. The log line says which bound actually ended the read.
    monkeypatch.setattr(ssc_client, "_MAX_RESPONSE_BYTES", 4096)

    async def _handle(reader, writer):
        await reader.readline()
        # Never the requested path, so only a limit can end this - and all of
        # it up front, so the size limit is reached without racing the settle
        # window.
        for _ in range(50):
            writer.write(json.dumps({"noise": {"value": "x" * 500}}).encode() + b"\r\n")
        await writer.drain()
        await _stay_open()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = SSCClient(host="127.0.0.1", port=port, timeout=5.0, settle_time=_SETTLE)
    try:
        with caplog.at_level(logging.WARNING, logger="custom_components.neumann_kh.ssc_client"):
            await asyncio.wait_for(client.get(("device", "name")), timeout=5)
        assert client._writer is None, "the connection survived the size limit"
        assert any("bytes in one response" in r.message for r in caplog.records), (
            "the read ended on the line cap, not the size limit"
        )
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_a_line_that_is_not_utf8_is_skipped(socket_enabled):
    """json.loads decodes the bytes itself, so invalid UTF-8 raises before it.

    Only JSONDecodeError was caught, so a device emitting a stray byte took
    the whole request down instead of the one unusable line.
    """
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"\xff\xfe not utf-8 at all\r\n")
        writer.write(json.dumps({"device": {"name": "ok"}}).encode() + b"\r\n")
        await writer.drain()
        await _stay_open()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        assert await client.get(("device", "name")) == "ok"
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_a_reset_while_reading_becomes_a_connection_error(socket_enabled):
    """readuntil() can raise a bare ConnectionResetError.

    Untranslated it escapes past the handler in _locked_request that drops the
    socket, so the dead connection stays in place - and the coordinator, which
    only special-cases the SSC errors, logs a traceback for every remaining
    path of the cycle instead of failing it once.
    """
    async def _handle(reader, writer):
        await reader.readline()
        # Abort rather than close: SO_LINGER 0 makes the peer see a reset
        # while it is blocked in readuntil(), not a clean EOF.
        sock = writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        writer.close()

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = _client(port)
    try:
        with pytest.raises(SSCConnectionError):
            await client.get(("device", "name"))
        assert client._writer is None, "the dead connection was kept"
    finally:
        await client.close()
        await _shutdown(raw_server, handled)


async def test_a_slow_endless_talker_is_ended_by_the_time_limit(
    socket_enabled, monkeypatch, caplog
):
    """The only bound that catches a device talking slowly but forever.

    The line and byte caps need volume; a device that answers just often
    enough to refresh the settle window reaches neither. The time limit is
    what ends that read - and, just as importantly, drops the connection,
    because unread lines are still queued on the socket.

    Disabling that branch left every other test in this file green, and the
    read then ended through the settle timeout instead: bounded in time, but
    with the connection kept and nothing logged.
    """
    monkeypatch.setattr(ssc_client, "_MAX_READ_SECONDS", 0.5)

    async def _handle(reader, writer):
        await reader.readline()
        # Faster than the settle window, so the read never ends on its own,
        # and far too slow to reach the line or byte cap within the limit.
        while True:
            writer.write(json.dumps({"other": {"value": 1}}).encode() + b"\r\n")
            await writer.drain()
            await asyncio.sleep(_SETTLE / 5)

    raw_server, handled = await _serve(_handle)
    port = raw_server.sockets[0].getsockname()[1]
    client = SSCClient(host="127.0.0.1", port=port, timeout=5.0, settle_time=_SETTLE)
    try:
        with caplog.at_level(logging.WARNING):
            assert await client.get(("device", "name")) is None
        assert "kept sending for" in caplog.text, (
            f"the read ended through another path: {caplog.text}"
        )
        assert client._writer is None, "the connection was kept despite the limit"
    finally:
        await client.close()
        await _shutdown(raw_server, handled)
