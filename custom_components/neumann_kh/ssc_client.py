"""Eigenständiger asyncio-Client für das Sennheiser Sound Control Protocol (SSC).

Neumann KH DSP Lautsprecher (KH 80, KH 120 II, KH 150, KH 750 DSP, ...) werden
über SSC gesteuert: JSON-Nachrichten über eine TCP-Verbindung (Standardport 45),
jede Nachricht durch "\\r\\n" oder "\\n" abgeschlossen (siehe Sennheiser SSC
Developer's Guide, Abschnitt "TCP/IP").

Eine "get"-Anfrage wird gestellt, indem der gewünschte Pfad mit dem JSON-Wert
`null` angefragt wird, z. B. {"audio":{"out":{"mute":null}}}.
Eine "set"-Anfrage liefert stattdessen den gewünschten Wert, z. B.
{"audio":{"out":{"mute":true}}}.

Fragt man einen Container (z. B. {"audio":null}) statt eines einzelnen Blattes
ab, antwortet das Gerät mit MEHREREN einzelnen JSON-Zeilen (einer je Blatt) -
das ist in freier Wildbahn bei khtool zu beobachten. Dieser Client sammelt
deshalb bei get-Anfragen so lange Antwortzeilen ein, bis für eine kurze
"Beruhigungszeit" (settle time) keine neue Zeile mehr eintrifft.

Wichtig für IPv6 Link-Local Adressen (fe80::...): Diese benötigen eine
Scope-ID (Interface-Name), sonst kann das Betriebssystem die Route nicht
auflösen. Der Client hängt die Scope-ID automatisch an, falls eine
Link-Local-Adresse übergeben wurde und noch keine Scope-ID enthalten ist.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Trennzeichen lt. SSC-Spezifikation: CR+LF oder LF alleine sind erlaubt.
_MESSAGE_TERMINATOR = b"\n"


class SSCConnectionError(Exception):
    """Wird ausgelöst, wenn keine Verbindung zum Lautsprecher hergestellt werden kann."""


class SSCTimeoutError(Exception):
    """Wird ausgelöst, wenn innerhalb der Timeout-Zeit keine Antwort eintrifft."""


class SSCDeviceError(Exception):
    """Wird ausgelöst, wenn das Gerät eine Anfrage explizit ablehnt (OSC-Fehlerantwort).

    Beispiel (per echtem Hardware-Test bestätigt): Fragt man einen auf dem
    Gerät nicht existierenden Pfad ab oder setzt ihn, antwortet die KH 120 II
    mit {"osc":{"error":[400,{"desc":"message not understood"}]}} statt mit
    dem erwarteten Wert. Ohne diese Erkennung würde ein solcher Fehler
    unbemerkt im Ergebnis-Dict landen, statt dem Aufrufer klar zu signalisieren,
    dass die Anfrage abgelehnt wurde.
    """


def _deep_merge(target: dict, source: dict) -> None:
    """Führt zwei verschachtelte Dicts zusammen (in-place), source gewinnt bei Konflikten."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _build_nested(path: tuple[str, ...], value: Any) -> dict:
    """Baut aus einem Pfad-Tupel und einem Wert ein verschachteltes SSC-JSON-Objekt.

    Beispiel: _build_nested(("audio", "out", "mute"), True)
              -> {"audio": {"out": {"mute": True}}}
    """
    node: dict[str, Any] = {}
    root = node
    for part in path[:-1]:
        node[part] = {}
        node = node[part]
    node[path[-1]] = value
    return root


def _extract(data: dict, path: tuple[str, ...]) -> Any:
    """Liest einen Wert aus einem verschachtelten Dict anhand eines Pfad-Tupels."""
    node: Any = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class SSCClient:
    """Hält eine TCP-Verbindung zu genau einem SSC-Server (Lautsprecher)."""

    def __init__(
        self,
        host: str,
        port: int,
        interface: str | None = None,
        timeout: float = 3.0,
        settle_time: float = 0.4,
    ) -> None:
        self._host = host
        self._port = port
        self._interface = interface
        self._timeout = timeout
        self._settle_time = settle_time
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def _connect_host(self) -> str:
        """Hängt bei Link-Local-Adressen (fe80::...) die Scope-ID (Interface) an."""
        host = self._host
        if host.lower().startswith("fe80") and "%" not in host and self._interface:
            return f"{host}%{self._interface}"
        return host

    async def _ensure_connected(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host=self._connect_host, port=self._port),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise SSCConnectionError(
                f"Verbindung zu {self._connect_host}:{self._port} fehlgeschlagen: {err}"
            ) from err

    async def close(self) -> None:
        """Schließt die Verbindung (z. B. beim Entladen der Integration)."""
        async with self._lock:
            if self._writer is not None:
                self._writer.close()
                try:
                    await self._writer.wait_closed()
                except OSError:
                    pass
                self._writer = None
                self._reader = None

    async def _send_raw(self, payload: dict) -> None:
        assert self._writer is not None
        message = json.dumps(payload).encode("utf-8") + b"\r\n"
        self._writer.write(message)
        await self._writer.drain()

    async def _read_lines_until_settled(self) -> list[dict]:
        """Liest Zeilen, bis für `settle_time` Sekunden nichts Neues mehr ankommt."""
        assert self._reader is not None
        results: list[dict] = []
        while True:
            try:
                raw_line = await asyncio.wait_for(
                    self._reader.readuntil(_MESSAGE_TERMINATOR),
                    timeout=self._settle_time if results else self._timeout,
                )
            except asyncio.TimeoutError:
                if not results:
                    raise SSCTimeoutError(
                        f"Keine Antwort von {self._host} innerhalb {self._timeout}s"
                    )
                break
            except asyncio.IncompleteReadError as err:
                if err.partial:
                    raw_line = err.partial
                else:
                    raise SSCConnectionError(f"Verbindung zu {self._host} unterbrochen") from err

            line = raw_line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                _LOGGER.debug("Ungültige SSC-Antwort von %s ignoriert: %s", self._host, line)
        return results

    async def request(self, payload: dict) -> dict:
        """Sendet eine SSC-Nachricht und liefert das (ggf. zusammengeführte) Ergebnis-Dict."""
        async with self._lock:
            await self._ensure_connected()
            try:
                await self._send_raw(payload)
                lines = await self._read_lines_until_settled()
            except (SSCConnectionError, SSCTimeoutError):
                # Verbindung verwerfen, damit beim nächsten Versuch neu verbunden wird
                if self._writer is not None:
                    self._writer.close()
                self._writer = None
                self._reader = None
                raise

            merged: dict[str, Any] = {}
            for line in lines:
                _deep_merge(merged, line)

            osc_error = _extract(merged, ("osc", "error"))
            if osc_error:
                # Format lt. Testergebnis: [400, {"desc": "message not understood"}]
                description = ""
                if isinstance(osc_error, list):
                    for part in osc_error:
                        if isinstance(part, dict) and "desc" in part:
                            description = part["desc"]
                raise SSCDeviceError(
                    f"Gerät {self._host} hat die Anfrage abgelehnt: "
                    f"{description or osc_error}"
                )

            return merged

    async def get(self, path: tuple[str, ...]) -> Any:
        """Fragt einen einzelnen Wert ab (get = Anfrage mit JSON null)."""
        response = await self.request(_build_nested(path, None))
        return _extract(response, path)

    async def set(self, path: tuple[str, ...], value: Any) -> Any:
        """Setzt einen Wert und gibt den vom Gerät bestätigten Wert zurück."""
        response = await self.request(_build_nested(path, value))
        return _extract(response, path)

    @staticmethod
    def extract(data: dict, path: tuple[str, ...]) -> Any:
        """Öffentlicher Zugriff auf _extract, für die Auswertung von request()-Ergebnissen."""
        return _extract(data, path)
