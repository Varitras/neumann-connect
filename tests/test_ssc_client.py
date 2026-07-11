"""Tests für den SSC-Client gegen einen echten lokalen asyncio-TCP-Server.

Kurze Timeouts (settle 0.05 s, timeout 0.3 s), damit die Suite schnell bleibt -
die echten Produktiv-Werte (DEFAULT_QUERY_SETTLE, 3 s Timeout) werden hier
bewusst nicht verwendet.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from custom_components.neumann_kh.ssc_client import (
    SSCClient,
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
)

# Das HA-Test-Plugin blockiert Sockets standardmäßig (keine echten
# Netzwerkzugriffe in Tests). Diese Tests nutzen bewusst einen lokalen
# TCP-Server auf Loopback - Sockets daher gezielt über die
# socket_enabled-Fixture (pytest-socket) freigeben.

_SETTLE = 0.05
_TIMEOUT = 0.3


class FakeSSCServer:
    """Minimaler SSC-Server: pro Verbindung ein Handler, Antworten steuerbar."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.port: int = 0
        self.connections: int = 0
        # Antwort-Fabrik: bekommt die geparste Anfrage, liefert Liste von
        # Antwort-Objekten (je eines pro Zeile). None-Eintrag = keine Antwort.
        self.responder = self.echo_responder
        self.response_delay: float = 0.0

    @staticmethod
    def echo_responder(request: dict) -> list[dict | None]:
        """Standard: Anfrage unverändert zurückspiegeln (wie ein get/set-Echo)."""
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
            # wait_closed() kann unter Python 3.12 bei Servern ohne je
            # angenommene Verbindung haengen - hart begrenzen.
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
    # Gerät bestätigt einen anderen Wert als angefragt (z. B. Clamping).
    server.responder = lambda req: [{"audio": {"out": {"level": -60}}}]
    client = _client(server.port)
    try:
        assert await client.set(("audio", "out", "level"), -80) == -60
    finally:
        await client.close()


async def test_settle_merges_multiple_lines_last_wins(server):
    # Zwei Zeilen für denselben Pfad: die spätere gewinnt (deep_merge-Reihenfolge).
    server.responder = lambda req: [
        {"device": {"name": "alt"}},
        {"device": {"name": "neu"}},
    ]
    client = _client(server.port)
    try:
        assert await client.get(("device", "name")) == "neu"
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
    # Ungültige Zeile darf die gültige danach nicht verhindern.
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"NOT JSON\r\n")
        writer.write(json.dumps({"device": {"name": "ok"}}).encode() + b"\r\n")
        await writer.drain()
        # Verbindung offen lassen: der Client wartet nach der letzten Zeile
        # noch die Settle-Zeit - ein Server-Close in dieser Phase wäre
        # (korrekt) ein Verbindungsabbruch.

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


async def test_timeout_raises_and_drops_connection(server):
    # Server antwortet gar nicht -> SSCTimeoutError, Verbindung verworfen.
    server.responder = lambda req: [None]
    client = _client(server.port)
    try:
        with pytest.raises(SSCTimeoutError):
            await client.get(("device", "name"))
        assert client._writer is None  # noqa: SLF001 - gezielter Whitebox-Test
    finally:
        await client.close()


async def test_connection_refused_raises_connection_error(socket_enabled):
    # Port ohne Server.
    client = SSCClient(host="127.0.0.1", port=1, timeout=_TIMEOUT, settle_time=_SETTLE)
    with pytest.raises(SSCConnectionError):
        await client.get(("device", "name"))


async def test_cancelled_request_drops_connection_no_stale_bleed(server):
    """Härtungsregression: Abbruch verwirft die Verbindung.

    Die verspätete Antwort der abgebrochenen Anfrage darf der nächsten
    Anfrage nicht zugeordnet werden (v1.15.0-Härtung).
    """
    server.response_delay = 0.2  # Antwort kommt erst nach dem Abbruch
    server.responder = lambda req: [{"stale": {"value": 1}}]
    client = _client(server.port)
    try:
        task = asyncio.create_task(client.get(("stale", "value")))
        await asyncio.sleep(0.05)  # Anfrage ist raus, Antwort noch nicht da
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Verbindung muss verworfen sein.
        assert client._writer is None  # noqa: SLF001

        # Folgeanfrage: bekommt eine NEUE Verbindung und die korrekte Antwort.
        server.response_delay = 0.0
        server.responder = lambda req: [{"fresh": {"value": 2}}]
        assert await client.get(("fresh", "value")) == 2
        assert server.connections == 2
    finally:
        await client.close()


async def test_oversized_line_raises_connection_error(socket_enabled):
    # Zeile über dem StreamReader-Limit (1 MiB) ohne Terminator.
    async def _handle(reader, writer):
        await reader.readline()
        writer.write(b"x" * (1_100_000))  # kein \n
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
