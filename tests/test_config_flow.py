"""Tests for the config flow's device identification.

The integration deliberately does not reject devices of other manufacturers -
SSC is not Neumann-exclusive - it only flags them, so these tests pin down when
the flag is raised.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.neumann_kh.config_flow import DeviceIdentity  # noqa: E402
from custom_components.neumann_kh.const import (  # noqa: E402
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
)


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


# --- Reconfigure ----------------------------------------------------------
#
# Driven without a network: the flow only accepts IPv6 (the speakers are
# IPv6-only), while the test simulator has to bind IPv4 loopback because the
# HA test plugin allows nothing else. Patching the connection test keeps the
# focus on the flow logic - that the entry is updated in place and that another
# speaker is refused.

_EXISTING_SERIAL = "SIM0001234"


@pytest.fixture
def _custom_integration(enable_custom_integrations, mock_async_zeroconf):
    """Make the flow reachable without starting real mDNS discovery.

    enable_custom_integrations: HA only offers custom integration flows when
    asked to. mock_async_zeroconf: the manifest declares zeroconf, so starting
    a flow pulls in that dependency, which opens real sockets and fails under
    the HA test plugin.
    """
    yield


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="KH 120 II Right",
        unique_id=_EXISTING_SERIAL,
        data={
            CONF_HOST: "fe80::1",
            CONF_PORT: 45,
            CONF_INTERFACE: "eth0",
            CONF_MODEL: "KH 120 II",
            CONF_SERIAL: _EXISTING_SERIAL,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def _run_reconfigure(hass, entry, identity, host="fe80::2"):
    with patch(
        "custom_components.neumann_kh.config_flow._async_test_connection",
        return_value=identity,
    ):
        result = await entry.start_reconfigure_flow(hass)
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: host, CONF_INTERFACE: "eth1", CONF_PORT: 45},
        )


async def test_reconfigure_updates_the_entry_in_place(hass, _custom_integration):
    entry = _entry(hass)
    identity = DeviceIdentity(
        product="KH 120 II",
        serial=_EXISTING_SERIAL,
        version="1_7_4",
        vendor="Georg Neumann GmbH",
    )

    result = await _run_reconfigure(hass, entry, identity)

    assert result["type"] is FlowResultType.ABORT, result.get("errors")
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "fe80::2"
    assert entry.data[CONF_INTERFACE] == "eth1"
    # The whole point: same entry, so entity IDs and history survive.
    assert entry.unique_id == _EXISTING_SERIAL


async def test_reconfigure_refuses_a_different_speaker(hass, _custom_integration):
    """Repointing an entry at another unit would graft its history onto it."""
    entry = _entry(hass)
    identity = DeviceIdentity(
        product="KH 750", serial="SIM0007500", vendor="Georg Neumann GmbH"
    )

    result = await _run_reconfigure(hass, entry, identity)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "fe80::1"  # unchanged


async def test_reconfigure_refuses_a_device_without_a_serial(hass, _custom_integration):
    """A known serial must be matched, not merely "not contradicted".

    Accepting a device that reports no serial would attach this entry - its
    history and stored exports - to whatever happens to answer at the address.
    """
    entry = _entry(hass)
    identity = DeviceIdentity(product="KH 120 II", serial=None, vendor="Georg Neumann GmbH")

    result = await _run_reconfigure(hass, entry, identity)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "fe80::1"  # unchanged


async def test_reconfigure_rejects_link_local_without_interface(hass, _custom_integration):
    entry = _entry(hass)
    identity = DeviceIdentity(serial=_EXISTING_SERIAL, vendor="Georg Neumann GmbH")

    with patch(
        "custom_components.neumann_kh.config_flow._async_test_connection",
        return_value=identity,
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "fe80::2", CONF_INTERFACE: "", CONF_PORT: 45},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "interface_required_for_link_local"}
