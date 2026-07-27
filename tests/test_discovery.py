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
