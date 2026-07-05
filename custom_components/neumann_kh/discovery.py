"""Aktive mDNS/Zeroconf-Gerätesuche für Neumann KH (SSC) Lautsprecher.

Die SSC-Spezifikation (Sennheiser Sound Control Protocol) schreibt vor, dass
sich jedes SSC-Gerät, das TCP unterstützt, per DNS-SD (Apple Bonjour) unter
dem Dienst-Typ "_ssc._tcp.local." im Netzwerk bekannt macht - genau wie z. B.
AirPlay- oder Chromecast-Geräte.

Dieses Modul nutzt Home Assistants bereits laufende Zeroconf-Instanz (kein
zusätzlicher eigener mDNS-Listener), um für ein paar Sekunden aktiv nach
solchen Diensten zu suchen (Scan-Button im Config Flow statt automatischer
Hintergrund-Erkennung).

Wichtiger Vorteil ggü. der manuellen IP-Eingabe: Bei Link-Local-IPv6-Adressen
(fe80::...) liefert python-zeroconf über `parsed_scoped_addresses()` die
Adresse bereits inklusive Scope-ID (z. B. "fe80::...%3") - das manuelle
Auswählen des Netzwerk-Interfaces entfällt für automatisch gefundene Geräte.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import HomeAssistant
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from .const import SCAN_DURATION_SECONDS, SSC_ZEROCONF_SERVICE_TYPE

_LOGGER = logging.getLogger(__name__)

_RESOLVE_TIMEOUT_MS = 3000


@dataclass
class DiscoveredSpeaker:
    """Ein per mDNS gefundener SSC-Server-Kandidat (noch ohne Identitätsdaten)."""

    mdns_name: str  # vollständiger mDNS-Dienstname, z. B. "Right._ssc._tcp.local."
    host: str  # IP-Adresse; bei Link-Local inkl. "%<scope_id>"
    port: int


async def async_scan_for_speakers(
    hass: HomeAssistant, duration: float = SCAN_DURATION_SECONDS
) -> list[DiscoveredSpeaker]:
    """Sucht `duration` Sekunden lang aktiv nach SSC-Geräten im Netzwerk.

    Gibt eine Liste roher Kandidaten zurück (Adresse + Port), noch OHNE
    Identitätsabfrage (Modell/Seriennummer) - das übernimmt der Config Flow
    im Anschluss über den normalen SSCClient, da mDNS TXT-Records das nicht
    zuverlässig genug liefern.
    """
    aiozc = await ha_zeroconf.async_get_async_instance(hass)
    found_names: set[str] = set()

    def _on_change(_zeroconf, _service_type, name, state_change) -> None:  # noqa: ANN001
        # Signatur von zeroconf vorgegeben; nur `name` und `state_change`
        # werden benötigt, die übrigen Parameter sind mit "_" als ungenutzt
        # markiert.
        if state_change is ServiceStateChange.Added:
            found_names.add(name)

    browser = AsyncServiceBrowser(
        aiozc.zeroconf, SSC_ZEROCONF_SERVICE_TYPE, handlers=[_on_change]
    )
    try:
        await asyncio.sleep(duration)
    finally:
        await browser.async_cancel()

    speakers: list[DiscoveredSpeaker] = []
    for mdns_name in found_names:
        info = AsyncServiceInfo(SSC_ZEROCONF_SERVICE_TYPE, mdns_name)
        try:
            resolved = await info.async_request(aiozc.zeroconf, _RESOLVE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 - defensiv, einzelner Dienst soll den Scan nicht abbrechen
            _LOGGER.debug("Konnte mDNS-Dienst %s nicht auflösen", mdns_name, exc_info=True)
            continue

        if not resolved or info.port is None:
            continue

        addresses = info.parsed_scoped_addresses()
        if not addresses:
            continue

        # Feste (nicht Link-Local-) Adresse bevorzugen, falls vorhanden - sonst
        # die erste Link-Local-Adresse (bereits inkl. "%scope_id").
        host = next((addr for addr in addresses if "%" not in addr), addresses[0])

        speakers.append(DiscoveredSpeaker(mdns_name=mdns_name, host=host, port=info.port))

    return speakers
