"""Tests for address selection from an mDNS record.

SSC on these speakers is IPv6-only and the config flow rejects IPv4, so a
record that also carries an IPv4 address must not lead to it being picked.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.discovery import _pick_host  # noqa: E402


def test_ipv4_is_never_picked():
    # The old implementation took the first address without "%" - which is
    # exactly the IPv4 one here, failing later as "not a valid IPv6 address".
    assert _pick_host(["192.168.1.50", "fe80::1%eth0"]) == "fe80::1%eth0"


def test_global_ipv6_wins_over_link_local():
    # A global address needs no scope ID, so it is the better choice.
    assert _pick_host(["fe80::1%eth0", "2001:db8::1"]) == "2001:db8::1"


def test_first_link_local_is_kept_when_no_global_exists():
    assert _pick_host(["fe80::1%eth0", "fe80::2%eth0"]) == "fe80::1%eth0"


def test_ipv4_only_record_is_rejected():
    assert _pick_host(["192.168.1.50"]) is None


def test_empty_and_malformed_records_are_rejected():
    assert _pick_host([]) is None
    assert _pick_host(["not-an-address"]) is None
