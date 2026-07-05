"""DataUpdateCoordinator für die Neumann KH (SSC) Integration.

Der Coordinator bündelt das periodische Abfragen aller relevanten SSC-Werte
in einer Anfrage (get_many) und stellt sie den Entities als verschachteltes
Dict zur Verfügung. So wird nicht pro Entity eine eigene Netzwerkanfrage
nötig - wichtig, da SSC pro Gerät nur eine aktive TCP-Verbindung sinnvoll
unterstützt.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VENDOR,
    PATH_IDENTITY_VERSION,
    PATH_INPUT_GAIN,
    PATH_INPUT_PHASE_INVERT,
    PATH_LOGO_BRIGHTNESS,
    PATH_METER_INPUT_LEVEL,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_CORRECTION,
    PATH_OUTPUT_SOLO,
    UPDATE_INTERVAL_SECONDS,
)
from .ssc_client import SSCClient, SSCConnectionError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

# Pfade, die bei JEDEM Modell abgefragt werden.
_BASE_POLL_PATHS = [
    PATH_IDENTITY_VENDOR,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VERSION,
    PATH_INPUT_GAIN,
    PATH_INPUT_PHASE_INVERT,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_SOLO,
    PATH_OUTPUT_PHASE_CORRECTION,
]


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
        # ui/logo/brightness existiert lt. khtool-Doku nur bei KH 80/150/120 II,
        # NICHT bei KH 750 DSP - wird deshalb nur bei passendem Modell abgefragt,
        # um unnötige/fehlerhafte Anfragen an die KH 750 zu vermeiden.
        self._poll_paths = list(_BASE_POLL_PATHS)
        if model in MODELS_WITH_LOGO_AND_SAVE:
            self._poll_paths.append(PATH_LOGO_BRIGHTNESS)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fragt alle Werte + den Live-Eingangspegel ab."""
        try:
            data = await self.client.get_many(self._poll_paths)
            # Live-Pegelmessung separat, da eigener Adresszweig ("m" statt "audio")
            meter = await self.client.request({"m": {"audio": None}})
            data.setdefault("m", {})["audio"] = SSCClient.extract(meter, PATH_METER_INPUT_LEVEL)
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise UpdateFailed(f"Neumann KH nicht erreichbar: {err}") from err
        return data

    def value(self, path: tuple[str, ...]) -> Any:
        """Bequemer Zugriff auf einen Wert aus den zuletzt gepollten Daten."""
        if self.data is None:
            return None
        return SSCClient.extract(self.data, path)
