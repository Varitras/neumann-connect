"""Tests for address selection from an mDNS record.

SSC on these speakers is IPv6-only and the config flow rejects IPv4, so a
record that also carries an IPv4 address must not lead to it being picked.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.discovery import pick_host


def test_ipv4_is_never_picked():
    # The old implementation took the first address without "%" - which is
    # exactly the IPv4 one here, failing later as "not a valid IPv6 address".
    assert pick_host(["192.168.1.50", "fe80::1%eth0"]) == "fe80::1%eth0"


def test_link_local_wins_over_global():
    """A global address dies with the next ISP prefix change.

    Field report: after a forced reconnect every configured entry failed with
    "unreachable" because the stored global addresses still carried the old
    prefix. The speakers answered on link-local the whole time.
    """
    assert pick_host(["2001:db8::1", "fe80::1%eth0"]) == "fe80::1%eth0"
    # Order in the record must not matter.
    assert pick_host(["fe80::1%eth0", "2001:db8::1"]) == "fe80::1%eth0"


def test_global_is_used_when_no_link_local_exists():
    assert pick_host(["2001:db8::1", "2001:db8::2"]) == "2001:db8::1"


def test_first_link_local_is_kept_when_several_exist():
    assert pick_host(["fe80::1%eth0", "fe80::2%eth0"]) == "fe80::1%eth0"


def test_ipv4_only_record_is_rejected():
    assert pick_host(["192.168.1.50"]) is None


def test_empty_and_malformed_records_are_rejected():
    assert pick_host([]) is None
    assert pick_host(["not-an-address"]) is None


async def test_resolution_stops_at_a_bound(monkeypatch):
    """A segment full of stale records must not stall whatever waits on it.

    Records resolve one at a time with their own timeout, so an unbounded pass
    can hold a config flow - or the setup repair, which runs on every failed
    retry - for minutes.
    """
    from unittest.mock import AsyncMock, patch

    from custom_components.neumann_kh import discovery

    monkeypatch.setattr(discovery, "_MAX_RESOLVE_SERVICES", 3)
    resolved: list[str] = []

    class _FakeInfo:  # skipcq: PYL-R0201 - a stand-in, not a design
        port = 45

        def __init__(self, service_type, name):
            self.name = name

        async def async_request(self, zeroconf, timeout_ms):
            resolved.append(self.name)
            return True

        def parsed_scoped_addresses(self):
            return ["fe80::1%2"]

    class _FakeBrowser:  # skipcq: PYL-R0201 - a stand-in, not a design
        def __init__(self, *args, **kwargs):
            handlers = kwargs.get("handlers") or args[2]
            for index in range(10):
                handlers[0](
                    None, "_ssc._tcp.local.", f"s{index}._ssc._tcp.local.",
                    discovery.ServiceStateChange.Added,
                )

        async def async_cancel(self):
            return None

    hass = AsyncMock()
    with patch.object(discovery, "AsyncServiceBrowser", _FakeBrowser), patch.object(
        discovery, "AsyncServiceInfo", _FakeInfo
    ), patch.object(discovery.ha_zeroconf, "async_get_async_instance", AsyncMock()):
        speakers = await discovery.async_scan_for_speakers(hass, duration=0)

    assert len(resolved) == 3, "the resolution pass was not bounded"
    assert len(speakers) == 3
