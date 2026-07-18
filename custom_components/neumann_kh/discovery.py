"""Active mDNS/Zeroconf device search for Neumann KH (SSC) speakers.

SSC devices announce themselves via DNS-SD under "_ssc._tcp.local.". Uses
Home Assistant's running Zeroconf instance for a time-limited active scan
(scan button in the config flow, no background discovery).
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
    """An SSC server candidate found via mDNS (still without identity data)."""

    mdns_name: str  # full mDNS service name, e.g. "Right._ssc._tcp.local."
    host: str  # IP address; for link-local incl. "%<scope_id>"
    port: int


async def async_scan_for_speakers(
    hass: HomeAssistant, duration: float = SCAN_DURATION_SECONDS
) -> list[DiscoveredSpeaker]:
    """Actively search the network for SSC devices for `duration` seconds.

    Returns only address + port; the identity query (model/serial number) is
    handled afterwards by the config flow via the normal SSCClient.
    """
    aiozc = await ha_zeroconf.async_get_async_instance(hass)
    found_names: set[str] = set()

    def _on_change(zeroconf, service_type, name, state_change) -> None:  # noqa: ANN001
        # Parameter names must be exactly these - zeroconf calls with keyword
        # arguments, renaming breaks the callback (see 1.8.1).
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
        except Exception:  # noqa: BLE001 - defensive, a single service should not abort the scan
            _LOGGER.debug("Could not resolve mDNS service %s", mdns_name, exc_info=True)
            continue

        if not resolved or info.port is None:
            continue

        addresses = info.parsed_scoped_addresses()
        if not addresses:
            continue

        # Prefer a fixed (non-link-local) address if available - otherwise the
        # first link-local address (already incl. "%scope_id").
        host = next((addr for addr in addresses if "%" not in addr), addresses[0])

        speakers.append(DiscoveredSpeaker(mdns_name=mdns_name, host=host, port=info.port))

    return speakers
