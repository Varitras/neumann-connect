"""Tests for the config flow's device identification.

The integration deliberately does not reject devices of other manufacturers -
SSC is not Neumann-exclusive - it only flags them, so these tests pin down when
the flag is raised.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.config_flow import DeviceIdentity  # noqa: E402


def test_neumann_vendor_is_recognised():
    # Exact string reported by both test devices (KH 120 II and KH 750).
    identity = DeviceIdentity(product="KH 120 II", vendor="Georg Neumann GmbH")
    assert identity.is_neumann


def test_vendor_match_is_case_insensitive_and_substring():
    assert DeviceIdentity(vendor="NEUMANN").is_neumann
    assert DeviceIdentity(vendor="Georg Neumann GmbH, Berlin").is_neumann


def test_foreign_vendor_is_flagged():
    assert not DeviceIdentity(product="EW-DX EM 2", vendor="Sennheiser").is_neumann


def test_missing_vendor_field_counts_as_neumann():
    # The field is verified on the KH 120 II and KH 750 only. A model that does
    # not expose it must not be flagged - absence is inconclusive, and treating
    # it as foreign would nag users of untested Neumann models.
    assert DeviceIdentity(product="KH 310").is_neumann


def test_error_result_carries_no_identity():
    identity = DeviceIdentity(error_key="cannot_connect")
    assert identity.error_key == "cannot_connect"
    assert identity.product is None
    assert identity.serial is None
    assert identity.vendor is None
