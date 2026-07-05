"""Eigenständiger asyncio-Client für das Sennheiser Sound Control Protocol (SSC).

Neumann KH DSP Lautsprecher (KH 80, KH 120 II, KH 150, KH 750 DSP, ...) werden
über SSC gesteuert: JSON-Nachrichten über eine TCP-Verbindung (Standardport 45),
jede Nachricht durch "\\r\\n" oder "\\n" abgeschlossen (siehe Sennheiser SSC
Developer's Guide, Abschnitt "TCP/IP").

Eine "get"-Anfrage wird gestellt, indem der gewünschte Pfad mit dem JSON-Wert
`null` angefragt wird, z. B. {"audio":{"out":{"mute":null}}}.
Eine "set"-Anfrage liefert stattdessen den gewünschten Wert, z. B.
{"audio":{"out":{"mute":true}}}.

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

from ._util import build_nested, deep_merge, extract

_LOGGER = logging.getLogger(__name__)

# Trennzeichen lt. SSC-Spezifikation: CR+LF oder LF alleine sind erlaubt.
_MESSAGE_TERMINATOR = b"\n"

# Schutz gegen übermäßig große/nie terminierte Antworten (siehe
# SSCConnectionError-Handling in _read_lines_until_settled). Deutlich über
# jeder realistischen SSC-Antwort (auch der volle -q-Dump ist <<1 MB).
_MAX_LINE_BYTES = 1_048_576  # 1 MiB


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
        # Priority-Mechanismus (siehe request(priority=True) und
        # yield_if_priority_waiting()): Wird gesetzt, sobald eine Nutzeraktion
        # (set) auf den Lock wartet, während ein langer Poll-Zyklus läuft. Der
        # Poll prüft dieses Flag zwischen seinen Einzelabfragen und gibt dann
        # den Lock kurz frei, damit die Nutzeraktion sofort drankommt, statt
        # den gesamten restlichen Poll-Zyklus abwarten zu müssen.
        self._priority_waiting = asyncio.Event()

    @property
    def priority_waiting(self) -> asyncio.Event:
        """Event, das anzeigt, dass eine Nutzeraktion auf den Lock wartet."""
        return self._priority_waiting

    @property
    def _connect_host(self) -> str:
        """Hängt bei Link-Local-Adressen (fe80::/10) die Scope-ID (Interface) an.

        IPv6 Link-Local umfasst laut RFC 4291 den Bereich fe80::/10, also die
        Präfixe fe80 bis febf. In der Praxis vergeben alle bekannten KH-Geräte
        zwar fe80, aber die Prüfung deckt den vollständigen Standardbereich ab.
        Eine Scope-ID (z. B. "%eth0") wird nur angehängt, wenn die Adresse
        noch keine enthält und ein Interface bekannt ist - ohne Scope-ID kann
        das Betriebssystem eine Link-Local-Route nicht auflösen.
        """
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
        """Sendet eine SSC-Nachricht und liefert das (ggf. zusammengeführte) Ergebnis-Dict.

        priority=True markiert eine Nutzeraktion (set/get, die auf eine direkte
        Reaktion wartet). Läuft gerade ein langer Poll-Zyklus, der den Lock
        hält, wird ihm über `_priority_waiting` signalisiert, den Lock nach
        seiner nächsten Einzelabfrage kurz freizugeben - so wartet die
        Nutzeraktion maximal eine Abfrage lang statt den gesamten restlichen
        Zyklus. Das Flag wird zurückgesetzt, sobald diese Aktion den Lock
        tatsächlich erhalten hat.
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
                if self._writer is not None:
                    self._writer.close()
                self._writer = None
                self._reader = None
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
        """Setzt einen Wert und gibt den vom Gerät bestätigten Wert zurück.

        priority=True als Default, da ein "set" praktisch immer eine direkte
        Nutzeraktion ist, die eine unmittelbare Reaktion erwartet.
        """
        response = await self.request(build_nested(path, value), priority=priority)
        return extract(response, path)

    @staticmethod
    def extract(data: dict, path: tuple[str, ...]) -> Any:
        """Öffentlicher Zugriff auf extract(), für die Auswertung von request()-Ergebnissen."""
        return extract(data, path)
