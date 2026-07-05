"""DataUpdateCoordinator für die Neumann KH (SSC) Integration.

Der Coordinator fragt bei jedem Poll-Zyklus die relevanten SSC-Container
(device, ui, audio, m) EINZELN ab, statt einzelne Blattwerte in einer
einzigen Sammelnachricht zu kombinieren.

Hintergrund (per echtem Hardware-Test mit khtool bestätigt): Referenziert
eine SSC-Anfrage auch nur EINEN nicht-existierenden Blattpfad, lehnt das
Gerät die GESAMTE Nachricht ab ("message not understood", OSC-Fehler 400) -
und zwar auch für alle anderen, eigentlich gültigen Werte in derselben
Nachricht. Eine Container-Abfrage (z. B. {"audio": null}) lässt das Gerät
dagegen selbst entscheiden, welche Blätter es zurückgibt - dadurch kann nie
ein falscher/veralteter Pfad die komplette Abfrage zum Scheitern bringen,
auch nicht bei künftigen Firmware-/Modellabweichungen.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import SSC_POLL_CONTAINERS, UPDATE_INTERVAL_SECONDS
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fragt jeden Container einzeln ab und führt die Ergebnisse zusammen.

        Da jeder Container unter einem eigenen, disjunkten Top-Level-Schlüssel
        antwortet (z. B. {"audio": {...}} bzw. {"ui": {...}}), reicht ein
        einfaches dict.update() zum Zusammenführen - es gibt keine
        Schlüssel-Überschneidungen zwischen den Containern.
        """
        merged: dict[str, Any] = {}
        try:
            for container in SSC_POLL_CONTAINERS:
                result = await self.client.request({container: None})
                merged.update(result)
        except (SSCConnectionError, SSCTimeoutError, SSCDeviceError) as err:
            raise UpdateFailed(f"Neumann KH nicht erreichbar: {err}") from err
        return merged

    def value(self, path: tuple[str, ...]) -> Any:
        """Bequemer Zugriff auf einen Wert aus den zuletzt gepollten Daten."""
        if self.data is None:
            return None
        return SSCClient.extract(self.data, path)
