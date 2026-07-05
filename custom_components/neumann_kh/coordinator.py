"""DataUpdateCoordinator für die Neumann KH (SSC) Integration.

Fragt bei jedem Poll-Zyklus jeden Wert einzeln ab (eine SSC-Nachricht pro
Blattpfad). Sammelnachrichten und Container-Abfragen (z. B. {"device":null})
werden von der Firmware abgelehnt - nur einzelne, konkrete Blattpfade
funktionieren zuverlässig.

Fehlerbehandlung: Verbindungsfehler lassen den ganzen Zyklus fehlschlagen.
Ein abgelehnter/fehlerhafter Einzelpfad wird übersprungen, die übrigen Werte
werden trotzdem aktualisiert. Ein Zeitlimit (POLL_CYCLE_TIMEOUT_SECONDS)
verhindert, dass ein hängendes Gerät den Zyklus blockiert.
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
from .eq_containers import eq_containers_for_model
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
        # Logo-Helligkeit nur bei passenden Modellen (nicht KH 750).
        if model in MODELS_WITH_LOGO_AND_SAVE:
            self._poll_paths.append(PATH_LOGO_BRIGHTNESS)
        # Subwoofer-spezifische Pfade nur bei erkanntem Subwoofer.
        if model in MODELS_WITH_SUBWOOFER_FEATURES:
            self._poll_paths.extend(SUBWOOFER_POLL_PATHS)
        # EQ-"enabled"-Arrays für die Band-Ein/Aus-Schalter (siehe eq.py).
        for container in eq_containers_for_model(model):
            self._poll_paths.append(container.path + ("enabled",))

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
                # Priority-Pfad: wartende Nutzeraktion kurz vorlassen.
                if self.client.priority_waiting.is_set():
                    await asyncio.sleep(0.05)

                try:
                    value = await self.client.get(path)
                except SSCDeviceError:
                    # Pfad von diesem Gerät nicht unterstützt - überspringen.
                    reachable = True
                    _LOGGER.debug(
                        "Pfad %s wird vom Gerät nicht unterstützt, überspringe", path
                    )
                    continue
                except (SSCConnectionError, SSCTimeoutError):
                    # Verbindungsproblem betrifft den ganzen Zyklus, nicht nur
                    # diesen einen Pfad - weiterreichen an die äußere
                    # Behandlung, statt für jeden verbleibenden Pfad erneut
                    # denselben Fehler zu loggen und einen neuen (ebenfalls
                    # scheiternden) Verbindungsversuch zu starten.
                    raise
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
            raise UpdateFailed("Neumann KH: keine der abgefragten Eigenschaften war erreichbar")

        return merged

    def value(self, path: tuple[str, ...]) -> Any:
        """Bequemer Zugriff auf einen Wert aus den zuletzt gepollten Daten."""
        if self.data is None:
            return None
        return SSCClient.extract(self.data, path)
