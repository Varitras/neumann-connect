"""Active mDNS/Zeroconf device search for Neumann KH (SSC) speakers.

SSC devices announce themselves via DNS-SD under "_ssc._tcp.local.". Uses
Home Assistant's running Zeroconf instance for a time-limited active scan
(scan button in the config flow, no background discovery).
"""

from __future__ import annotations

import asyncio
import ipaddress
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


def _pick_host(addresses: list[str]) -> str | None:
    """Choose the address to connect to from an mDNS record.

    SSC on these speakers is IPv6-only and the config flow rejects IPv4, so an
    IPv4 record must not be picked - it would fail later with a confusing
    "not a valid IPv6 address". A global IPv6 address is preferred over a
    link-local one because it needs no scope ID. Returns None if the record
    holds no IPv6 address at all.
    """
    link_local: str | None = None
    for address in addresses:
        # parsed_scoped_addresses() appends "%<scope_id>" to link-local entries.
        bare, _, _ = address.partition("%")
        try:
            parsed = ipaddress.ip_address(bare)
        except ValueError:
            continue
        if parsed.version != 6:
            continue
        if not parsed.is_link_local:
            return address
        if link_local is None:
            link_local = address
    return link_local


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

        host = _pick_host(info.parsed_scoped_addresses())
        if host is None:
            _LOGGER.debug("mDNS service %s announced no IPv6 address", mdns_name)
            continue

        speakers.append(DiscoveredSpeaker(mdns_name=mdns_name, host=host, port=info.port))

    return speakers
