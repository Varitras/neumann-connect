"""DataUpdateCoordinator für die Neumann KH (SSC) Integration.

Der Coordinator fragt bei jedem Poll-Zyklus JEDEN benötigten Wert EINZELN
und explizit ab (eine eigene SSC-Nachricht pro Blattpfad).

Hintergrund (per echtem Hardware-Test mit khtool bestätigt, zwei gescheiterte
Zwischenschritte):
1. Eine Sammelnachricht mit mehreren Blättern wird von der Firmware komplett
   abgelehnt, sobald auch nur EIN Blatt darin unbekannt ist
   ("message not understood", OSC-Fehler 400) - und zwar für ALLE Werte in
   der Nachricht, nicht nur den fehlerhaften.
2. Eine Container-Abfrage wie {"device":null} (in der Annahme, das Gerät
   würde automatisch alle vorhandenen Blätter darunter zurückgeben) wird
   ebenfalls abgelehnt ("address not found", OSC-Fehler 404).
Einzig einzelne, konkrete, nachweislich existierende Blattpfade funktionieren
zuverlässig - das macht auch khtool laut eigenem Log
("Reading available commands ... from khtool_commands.json") tatsächlich so:
pro Modell/Firmware eine Liste bekannter Einzelpfade, jeweils separat
abgefragt.

Fehlerbehandlung (drei Stufen):
- Verbindungsfehler (Gerät nicht erreichbar, Timeout): lässt den GESAMTEN
  Poll-Zyklus fehlschlagen (UpdateFailed) - deutet auf ein echtes
  Erreichbarkeitsproblem hin.
- Gerät lehnt EINEN einzelnen Pfad ab (SSCDeviceError, z. B. weil dieses
  Modell/diese Firmware die Eigenschaft nicht unterstützt - wie "dimm" auf
  der KH 120 II): nur dieser eine Wert wird übersprungen (Debug-Log), die
  übrigen Werte werden trotzdem aktualisiert.
- Unerwarteter Fehler bei einem einzelnen Pfad (z. B. ein Bug in einer
  zukünftigen Änderung): wird geloggt und übersprungen, statt den gesamten
  Poll-Zyklus (und damit alle Entities) mitzureißen.

Zusätzlich begrenzt ein Gesamt-Zeitlimit (POLL_CYCLE_TIMEOUT_SECONDS) die
Dauer eines kompletten Poll-Zyklus, damit ein "hängendes" (aber technisch
noch antwortendes) Gerät nicht beliebig lange blockiert.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._util import build_nested, deep_merge
from .const import (
    MODELS_WITH_LOGO_AND_SAVE,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_LOGO_BRIGHTNESS,
    POLL_CYCLE_TIMEOUT_SECONDS,
    POLL_PATHS,
    SUBWOOFER_POLL_PATHS,
    UPDATE_INTERVAL_SECONDS,
)
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)


class NeumannKHCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordiniert das Polling eines einzelnen Neumann KH Lautsprechers."""

    def __init__(
        self, hass: HomeAssistant, client: SSCClient, name: str, model: str | None = None
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"neumann_kh_{name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.client = client
        self.model = model
        self._poll_paths = list(POLL_PATHS)
        # ui/logo/brightness existiert lt. khtool-Doku nur bei KH 80/150/120 II,
        # NICHT bei KH 750 - wird deshalb nur bei passendem Modell abgefragt.
        if model in MODELS_WITH_LOGO_AND_SAVE:
            self._poll_paths.append(PATH_LOGO_BRIGHTNESS)
        # Subwoofer-spezifische Pfade (out1/out2, Temperatur, Ausgangs-
        # Metering, Subwoofer-UI-Werte) nur bei erkanntem Subwoofer abfragen.
        if model in MODELS_WITH_SUBWOOFER_FEATURES:
            self._poll_paths.extend(SUBWOOFER_POLL_PATHS)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fragt jeden Pfad einzeln ab; ein abgelehnter/fehlerhafter Einzelpfad wird übersprungen."""
        try:
            return await asyncio.wait_for(
                self._poll_all_paths(), timeout=POLL_CYCLE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as err:
            raise UpdateFailed(
                f"Neumann KH: Poll-Zyklus überschritt das Zeitlimit von "
                f"{POLL_CYCLE_TIMEOUT_SECONDS}s"
            ) from err

    async def _poll_all_paths(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        reachable = False
        try:
            for path in self._poll_paths:
                # Priority-Pfad (siehe SSCClient.request): Wartet gerade eine
                # Nutzeraktion (z. B. ein Schalter-Tastendruck) auf den Lock,
                # kurz pausieren. Das gibt den soeben (nach der letzten
                # Einzelabfrage) freigegebenen Lock der wartenden Nutzeraktion,
                # bevor der Poll ihn mit der nächsten Abfrage wieder greift -
                # so drängelt sich die Nutzeraktion zwischen zwei Poll-Abfragen
                # hinein, statt den gesamten restlichen Zyklus abzuwarten.
                if self.client.priority_waiting.is_set():
                    # Ein kurzes Nachgeben genügt: sleep(0) reicht nicht immer,
                    # da der Lock erst beim nächsten await-Punkt übernommen
                    # wird - ein minimaler realer Sleep gibt der wartenden
                    # Nutzeraktion zuverlässig den Vortritt.
                    await asyncio.sleep(0.05)

                try:
                    value = await self.client.get(path)
                except SSCDeviceError:
                    # Dieser einzelne Pfad wird vom Gerät nicht unterstützt -
                    # überspringen, aber mit den übrigen Pfaden weitermachen.
                    reachable = True  # Gerät hat geantwortet, also grundsätzlich erreichbar
                    _LOGGER.debug(
                        "Pfad %s wird vom Gerät nicht unterstützt, überspringe", path
                    )
                    continue
                except Exception:  # noqa: BLE001 - ein Bug bei einem Pfad soll nicht alle Werte mitreißen
                    _LOGGER.exception(
                        "Unerwarteter Fehler beim Abfragen von Pfad %s, überspringe", path
                    )
                    continue
                reachable = True
                deep_merge(merged, build_nested(path, value))
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise UpdateFailed(f"Neumann KH nicht erreichbar: {err}") from err

        if not reachable:
            # Keine einzige Anfrage war erfolgreich - eher ein echtes
            # Erreichbarkeitsproblem als lauter zufällig nicht unterstützte Pfade.
            raise UpdateFailed("Neumann KH: keine der abgefragten Eigenschaften war erreichbar")

        return merged

    def value(self, path: tuple[str, ...]) -> Any:
        """Bequemer Zugriff auf einen Wert aus den zuletzt gepollten Daten."""
        if self.data is None:
            return None
        return SSCClient.extract(self.data, path)
