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

Fehlerbehandlung: Ein genereller Verbindungsfehler (Gerät nicht erreichbar,
Timeout) lässt den GESAMTEN Poll-Zyklus fehlschlagen (UpdateFailed) - das
deutet auf ein echtes Erreichbarkeitsproblem hin. Lehnt das Gerät dagegen nur
EINEN einzelnen Pfad ab (SSCDeviceError, z. B. weil dieses Modell/diese
Firmware die Eigenschaft nicht unterstützt - wie "dimm" auf der KH 120 II),
wird nur dieser eine Wert übersprungen (Debug-Log) und die übrigen Werte
werden trotzdem aktualisiert.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_LOGO_BRIGHTNESS,
    POLL_PATHS,
    UPDATE_INTERVAL_SECONDS,
)
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)


def _build_nested(path: tuple[str, ...], value: Any) -> dict:
    """Baut aus einem Pfad-Tupel ein verschachteltes Dict (zum Zusammenführen der Ergebnisse)."""
    node: dict[str, Any] = {}
    root = node
    for part in path[:-1]:
        node[part] = {}
        node = node[part]
    node[path[-1]] = value
    return root


def _deep_merge(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


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
        # NICHT bei KH 750 DSP - wird deshalb nur bei passendem Modell abgefragt.
        if model in MODELS_WITH_LOGO_AND_SAVE:
            self._poll_paths.append(PATH_LOGO_BRIGHTNESS)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fragt jeden Pfad einzeln ab; ein abgelehnter Einzelpfad wird übersprungen."""
        merged: dict[str, Any] = {}
        reachable = False
        try:
            for path in self._poll_paths:
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
                reachable = True
                _deep_merge(merged, _build_nested(path, value))
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
