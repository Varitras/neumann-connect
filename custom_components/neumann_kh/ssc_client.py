"""Eigenständiger asyncio-Client für das Sennheiser Sound Control Protocol (SSC).

JSON über TCP (Standardport 45), jede Nachricht mit "\\r\\n" oder "\\n"
abgeschlossen. "get" = Pfad mit Wert `null` anfragen, "set" = Pfad mit
gewünschtem Wert senden.

IPv6 Link-Local-Adressen (fe80::...) brauchen eine Scope-ID (Interface) -
wird automatisch angehängt, falls nötig.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from ._util import build_nested, deep_merge, extract
from .const import DEFAULT_QUERY_SETTLE

_LOGGER = logging.getLogger(__name__)

# Trennzeichen lt. SSC-Spezifikation: CR+LF oder LF alleine sind erlaubt.
_MESSAGE_TERMINATOR = b"\n"

# Schutz gegen übermäßig große/nie terminierte Antworten: wird als explizites
# StreamReader-Limit gesetzt (readuntil wirft oberhalb LimitOverrunError, siehe
# _read_lines_until_settled). Deutlich über jeder realistischen SSC-Antwort
# (auch der volle -q-Dump ist <<1 MB).
_MAX_LINE_BYTES = 1_048_576  # 1 MiB


class SSCConnectionError(Exception):
    """Wird ausgelöst, wenn keine Verbindung zum Lautsprecher hergestellt werden kann."""


class SSCTimeoutError(Exception):
    """Wird ausgelöst, wenn innerhalb der Timeout-Zeit keine Antwort eintrifft."""


class SSCDeviceError(Exception):
    """Gerät lehnt die Anfrage ab (OSC-Fehlerantwort, z. B. Fehler 400/404/405)."""


class SSCClient:
    """Hält eine TCP-Verbindung zu genau einem SSC-Server (Lautsprecher)."""

    def __init__(
        self,
        host: str,
        port: int,
        interface: str | None = None,
        timeout: float = 3.0,
        settle_time: float = DEFAULT_QUERY_SETTLE,
    ) -> None:
        self._host = host
        self._port = port
        self._interface = interface
        self._timeout = timeout
        self._settle_time = settle_time
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        # Signalisiert dem Poll-Loop, dass eine Nutzeraktion auf den Lock
        # wartet (siehe request(priority=True)) - Poll gibt Lock dann frei.
        self._priority_waiting = asyncio.Event()

    @property
    def priority_waiting(self) -> asyncio.Event:
        """Event, das anzeigt, dass eine Nutzeraktion auf den Lock wartet."""
        return self._priority_waiting

    @property
    def _connect_host(self) -> str:
        """Hängt bei Link-Local-Adressen (fe80::/10, RFC 4291) die Scope-ID an."""
        host = self._host
        if "%" not in host and self._interface and self._is_link_local(host):
            return f"{host}%{self._interface}"
        return host

    @staticmethod
    def _is_link_local(host: str) -> bool:
        """Prüft, ob eine IPv6-Adresse im Link-Local-Bereich fe80::/10 liegt."""
        prefix = host.lower().split("%", 1)[0][:4]
        if len(prefix) < 4 or not prefix.startswith("fe"):
            return False
        # Drittes Hex-Zeichen muss im Bereich 8..b liegen (fe80..febf = /10).
        return prefix[2] in "89ab"

    async def _ensure_connected(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host=self._connect_host, port=self._port, limit=_MAX_LINE_BYTES
                ),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise SSCConnectionError(
                f"Verbindung zu {self._connect_host}:{self._port} fehlgeschlagen: {err}"
            ) from err

    def _drop_connection(self) -> None:
        """Verwirft die aktuelle Verbindung; der nächste Zugriff verbindet neu."""
        if self._writer is not None:
            self._writer.close()
        self._writer = None
        self._reader = None

    async def close(self) -> None:
        """Schließt die Verbindung (z. B. beim Entladen der Integration)."""
        async with self._lock:
            if self._writer is not None:
                self._writer.close()
                with contextlib.suppress(OSError):
                    await self._writer.wait_closed()
                self._writer = None
                self._reader = None

    async def _send_raw(self, payload: dict) -> None:
        if self._writer is None:
            # Sollte durch _ensure_connected() vor jedem Aufruf ausgeschlossen
            # sein - explizite Prüfung statt `assert`, da assert-Anweisungen
            # je nach Python-Startoptionen (-O) wegoptimiert werden können.
            raise SSCConnectionError(f"Keine aktive Verbindung zu {self._host}")
        message = json.dumps(payload).encode("utf-8") + b"\r\n"
        self._writer.write(message)
        await self._writer.drain()

    async def _read_lines_until_settled(self) -> list[dict]:
        """Liest Zeilen, bis für `settle_time` Sekunden nichts Neues mehr ankommt."""
        if self._reader is None:
            raise SSCConnectionError(f"Keine aktive Verbindung zu {self._host}")
        results: list[dict] = []
        while True:
            try:
                raw_line = await asyncio.wait_for(
                    self._reader.readuntil(_MESSAGE_TERMINATOR),
                    timeout=self._settle_time if results else self._timeout,
                )
            except asyncio.TimeoutError as err:
                if not results:
                    raise SSCTimeoutError(
                        f"Keine Antwort von {self._host} innerhalb {self._timeout}s"
                    ) from err
                break
            except asyncio.IncompleteReadError as err:
                if err.partial:
                    raw_line = err.partial
                else:
                    raise SSCConnectionError(f"Verbindung zu {self._host} unterbrochen") from err
            except asyncio.LimitOverrunError as err:
                # Antwort ohne Zeilenumbruch wurde unerwartet groß (deutlich
                # über jeder realistischen SSC-Nachricht) - Verbindung als
                # gestört behandeln, statt eine riesige/nie endende Zeile
                # weiter zu puffern.
                raise SSCConnectionError(
                    f"Antwort von {self._host} überschreitet Zeilenlimit"
                ) from err

            if len(raw_line) > _MAX_LINE_BYTES:
                raise SSCConnectionError(f"Antwort von {self._host} unplausibel groß")

            line = raw_line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                _LOGGER.debug("Ungültige SSC-Antwort von %s ignoriert: %s", self._host, line)
        return results

    async def request(self, payload: dict, priority: bool = False) -> dict:
        """Sendet eine SSC-Nachricht und liefert das zusammengeführte Ergebnis-Dict.

        priority=True markiert eine Nutzeraktion: läuft gerade ein Poll-Zyklus,
        wird ihm signalisiert, den Lock nach der aktuellen Einzelabfrage
        freizugeben, statt den ganzen Zyklus abzuwarten.
        """
        if priority:
            self._priority_waiting.set()
        async with self._lock:
            if priority:
                self._priority_waiting.clear()
            await self._ensure_connected()
            try:
                await self._send_raw(payload)
                lines = await self._read_lines_until_settled()
            except (SSCConnectionError, SSCTimeoutError):
                # Verbindung verwerfen, damit beim nächsten Versuch neu verbunden wird
                self._drop_connection()
                raise
            except asyncio.CancelledError:
                # Abbruch von außen (z. B. Zyklus-Zeitlimit im Coordinator): auf
                # dem Socket kann eine unbeantwortete Anfrage liegen. Verbindung
                # verwerfen, damit deren verspätete Antwort nicht der nächsten
                # Anfrage zugeordnet wird (falsche Werte/Fehler-Zuordnung).
                self._drop_connection()
                raise

            merged: dict[str, Any] = {}
            for line in lines:
                deep_merge(merged, line)

            osc_error = extract(merged, ("osc", "error"))
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

    async def get(self, path: tuple[str, ...], priority: bool = False) -> Any:
        """Fragt einen einzelnen Wert ab (get = Anfrage mit JSON null)."""
        response = await self.request(build_nested(path, None), priority=priority)
        return extract(response, path)

    async def set(self, path: tuple[str, ...], value: Any, priority: bool = True) -> Any:
        """Setzt einen Wert und gibt den vom Gerät bestätigten Wert zurück."""
        response = await self.request(build_nested(path, value), priority=priority)
        return extract(response, path)

    @staticmethod
    def extract(data: dict, path: tuple[str, ...]) -> Any:
        """Öffentlicher Zugriff auf extract(), für die Auswertung von request()-Ergebnissen."""
        return extract(data, path)
