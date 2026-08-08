"""Tests for the config flow's device identification.

The integration deliberately does not reject devices of other manufacturers -
SSC is not Neumann-exclusive - it only flags them, so these tests pin down when
the flag is raised.
"""

from __future__ import annotations

import json
from ipaddress import ip_address
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import (
    ZeroconfServiceInfo,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neumann_kh.config_flow import _SELECTED_DEVICE, DeviceIdentity
from custom_components.neumann_kh.const import (
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
    SSC_ZEROCONF_SERVICE_TYPE,
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
# What pick_host() returns for the announcement below: link-local, scope included.
_PICKED_HOST = "fe80::2%2"


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


async def _run_reconfigure(hass, entry, identity, host="fe80::2", interface="eth1"):
    with patch(
        "custom_components.neumann_kh.config_flow._async_test_connection",
        return_value=identity,
    ):
        result = await entry.start_reconfigure_flow(hass)
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: host, CONF_INTERFACE: interface, CONF_PORT: 45},
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


# --- Zeroconf: keeping a stored address current -----------------------------
#
# Field report behind these: after an ISP forced reconnect every entry failed
# to set up, because the stored global addresses still carried the old prefix.
# The speakers were reachable the whole time and kept announcing themselves.


def _zeroconf_info(
    host="fe80::2%2", serial=_EXISTING_SERIAL, port=45, model="KH 120 II"
):
    """An announcement shaped like the ones the real speakers send.

    Verified against all four devices on 2026-07-27: the TXT record carries
    the serial under "id", and the record holds the global address as well as
    the link-local one.
    """
    properties = {"txtvers": "1", "model": model, "sscvers": "1.1"}
    if serial is not None:
        properties["id"] = serial
    # Both addresses, global first - that is the order the real records use,
    # and picking the link-local one out of it is the behaviour under test.
    global_address = ip_address("2003:db8:1:1:2a36:38ff:fe12:3456")
    addresses = [global_address]
    if host:
        addresses.append(ip_address(host))
    return ZeroconfServiceInfo(
        # HA fills this with the first non-link-local address.
        ip_address=global_address,
        ip_addresses=addresses,
        port=port,
        hostname="KH120-SIMULATED.local.",
        type="_ssc._tcp.local.",
        name=f"KH120-SIMULATED-{serial}._ssc._tcp.local.",
        properties=properties,
    )


async def _run_zeroconf(hass, info, identity=None):
    # pick_host is deliberately NOT patched: which of the announced addresses
    # ends up stored is the point of the exercise.
    with patch(
        "custom_components.neumann_kh.config_flow._async_test_connection",
        return_value=identity or DeviceIdentity(error_key="cannot_connect"),
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
        )


async def test_zeroconf_corrects_a_stale_address(hass, _custom_integration):
    """The whole point: a changed address is adopted without asking.

    The speaker at the new address confirms its serial first - see
    test_zeroconf_verifies_before_repointing_an_entry for why.
    """
    entry = _entry(hass)
    assert entry.data[CONF_HOST] == "fe80::1"

    result = await _run_zeroconf(
        hass,
        _zeroconf_info(),
        identity=DeviceIdentity(
            product="KH 120 II", serial=_EXISTING_SERIAL, vendor="Georg Neumann GmbH"
        ),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == _PICKED_HOST
    # The scope ID travels inside the address, so the separate field is cleared
    # instead of being left to contradict it.
    assert entry.data[CONF_INTERFACE] == ""
    # Same entry - entity IDs and history survive.
    assert entry.unique_id == _EXISTING_SERIAL


async def test_zeroconf_leaves_a_matching_address_alone(hass, _custom_integration):
    entry = _entry(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_HOST: _PICKED_HOST, CONF_INTERFACE: ""}
    )

    result = await _run_zeroconf(hass, _zeroconf_info())
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == _PICKED_HOST


async def test_zeroconf_without_a_serial_is_ignored(hass, _custom_integration):
    """Matching by address is what produced the stale entries in the first place."""
    entry = _entry(hass)

    result = await _run_zeroconf(hass, _zeroconf_info(serial=None))
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_serial"
    assert entry.data[CONF_HOST] == "fe80::1"  # untouched


async def test_zeroconf_of_another_speaker_does_not_touch_this_entry(
    hass, _custom_integration
):
    entry = _entry(hass)

    result = await _run_zeroconf(
        hass,
        _zeroconf_info(serial="SIM0007500", model="KH 750"),
        identity=DeviceIdentity(
            product="KH 750", serial="SIM0007500", vendor="Georg Neumann GmbH"
        ),
    )
    await hass.async_block_till_done()

    # Unknown serial -> offered for setup, and this entry stays as it was.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert entry.data[CONF_HOST] == "fe80::1"


async def test_zeroconf_of_an_unknown_speaker_offers_setup(hass, _custom_integration):
    identity = DeviceIdentity(
        product="KH 120 II",
        serial="SIM0009999",
        version="1_7_4",
        vendor="Georg Neumann GmbH",
    )

    result = await _run_zeroconf(
        hass, _zeroconf_info(serial="SIM0009999"), identity=identity
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    # Creating the entry sets it up for real, which would open a socket.
    with patch(
        "custom_components.neumann_kh.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "New speaker"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == _PICKED_HOST
    assert result["data"][CONF_SERIAL] == "SIM0009999"


async def test_zeroconf_of_an_unreachable_device_is_dropped(hass, _custom_integration):
    """Announced but silent on SSC - do not offer it for setup."""
    result = await _run_zeroconf(hass, _zeroconf_info(serial="SIM0009999"))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


def test_manifest_declares_the_zeroconf_type():
    """Without this key Home Assistant never hands an announcement in.

    Every test above drives the flow directly, so all of them stay green even
    when the declaration is missing and the address correction is dead in the
    field. The service type is the one the speakers really announce, verified
    against all four devices on 2026-07-27.
    """
    manifest = json.loads(
        (
            Path(__file__).parent.parent
            / "custom_components"
            / "neumann_kh"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest.get("zeroconf") == [SSC_ZEROCONF_SERVICE_TYPE]


async def test_zeroconf_verifies_before_repointing_an_entry(hass, _custom_integration):
    """mDNS is unauthenticated - any host can claim any serial.

    Repointing an entry hands its history and its stored backups to whatever
    sits at the announced address, so the device has to confirm who it is
    before the address is written.
    """
    entry = _entry(hass)

    result = await _run_zeroconf(
        hass,
        _zeroconf_info(),  # claims the configured serial
        identity=DeviceIdentity(
            product="KH 120 II", serial="SIM0007500", vendor="Georg Neumann GmbH"
        ),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "fe80::1", "the entry was repointed on an unverified claim"


async def test_zeroconf_does_not_contact_a_speaker_that_has_not_moved(
    hass, _custom_integration
):
    """The common case by far: an announcement that changes nothing."""
    entry = _entry(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_HOST: _PICKED_HOST, CONF_INTERFACE: ""}
    )

    with patch(
        "custom_components.neumann_kh.config_flow._async_test_connection"
    ) as connect:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf_info()
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert not connect.called, "an unchanged announcement cost a network round trip"


async def test_zeroconf_anchors_on_the_serial_the_device_reports(hass, _custom_integration):
    """A record can be stale or wrong; the device is the authority.

    Storing the announced serial as the unique ID while the data carries the
    one the device reported would leave the entry contradicting itself.
    """
    identity = DeviceIdentity(
        product="KH 120 II", serial="SIM0009999", vendor="Georg Neumann GmbH"
    )

    result = await _run_zeroconf(
        hass, _zeroconf_info(serial="SIM0001111"), identity=identity
    )
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.neumann_kh.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "New speaker"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERIAL] == "SIM0009999"
    assert result["result"].unique_id == "SIM0009999"


# --- Identity values arrive as plain JSON, not necessarily as text ----------


@pytest.mark.parametrize(
    "raw",
    [[], {}, True, None, "", "   "],
)
def test_unusable_identity_values_become_none(raw):
    """A list or a dict reaches code that assumes text.

    The vendor check calls .lower(), the serial becomes a unique ID and a dict
    key, and mask_serial() slices it - each of which raises on the wrong type
    rather than reporting an unusable device.
    """
    from custom_components.neumann_kh.config_flow import _as_identity_text

    assert _as_identity_text(raw) is None


def test_a_numeric_serial_is_kept_as_text():
    """Real records carry the serial as a string, but a number still means one."""
    from custom_components.neumann_kh.config_flow import _as_identity_text

    assert _as_identity_text(1234567890) == "1234567890"
    assert _as_identity_text("  KH 120 II  ") == "KH 120 II"


async def test_zeroconf_of_a_device_without_a_serial_is_not_set_up(hass, _custom_integration):
    """Keeping the announced serial would make mDNS the device's identity.

    The record is unauthenticated, so a forged one could occupy a serial the
    real speaker needs later. The manual and reconfigure paths refuse a device
    that reports none, and this one has to as well.
    """
    identity = DeviceIdentity(
        product="KH 120 II", serial=None, vendor="Georg Neumann GmbH"
    )

    result = await _run_zeroconf(
        hass, _zeroconf_info(serial="SIM0009999"), identity=identity
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_serial"


# --- Manual setup ----------------------------------------------------------
#
# This path had no test at all, which is why it is written before touching the
# function: it is the way a user sets up the first speaker, and every one of
# these cases is a separate exit of the same nested chain.


async def _run_manual(hass, identity, user_input):
    """Open the manual step and submit `user_input`.

    async_setup_entry is stubbed out: on success Home Assistant sets the new
    entry up for real, and the coordinator would open a socket to a speaker
    that does not exist. What is under test is the flow, not the setup.
    """
    with (
        patch(
            "custom_components.neumann_kh.config_flow._async_test_connection",
            return_value=identity,
        ),
        patch(
            "custom_components.neumann_kh.async_setup_entry", return_value=True
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "manual"}
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )


_GOOD_IDENTITY = DeviceIdentity(
    product="KH 120 II",
    serial="SIM0001234",
    version="1_7_3",
    vendor="Georg Neumann GmbH",
)


async def test_manual_setup_creates_the_entry(hass, _custom_integration):
    result = await _run_manual(
        hass,
        _GOOD_IDENTITY,
        {
            CONF_NAME: "Left",
            CONF_HOST: "fe80::1",
            CONF_INTERFACE: "eth0",
            CONF_PORT: 45,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")
    assert result["title"] == "Left"
    assert result["data"][CONF_MODEL] == "KH 120 II"
    assert result["data"][CONF_SERIAL] == "SIM0001234"
    assert result["data"][CONF_INTERFACE] == "eth0"


async def test_manual_setup_needs_a_name(hass, _custom_integration):
    result = await _run_manual(
        hass,
        _GOOD_IDENTITY,
        {CONF_NAME: "   ", CONF_HOST: "fe80::1", CONF_INTERFACE: "eth0", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "name_required"}


async def test_manual_setup_rejects_a_non_ipv6_host(hass, _custom_integration):
    result = await _run_manual(
        hass,
        _GOOD_IDENTITY,
        {CONF_NAME: "Left", CONF_HOST: "192.168.1.5", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_ipv6"}


async def test_manual_setup_rejects_link_local_without_interface(hass, _custom_integration):
    """A fe80:: address needs a scope ID; no OS can route it otherwise."""
    result = await _run_manual(
        hass,
        _GOOD_IDENTITY,
        {CONF_NAME: "Left", CONF_HOST: "fe80::1", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "interface_required_for_link_local"}


async def test_manual_setup_takes_the_scope_id_out_of_the_host(hass, _custom_integration):
    """"fe80::1%eth0" in the address field is accepted and split."""
    result = await _run_manual(
        hass,
        _GOOD_IDENTITY,
        {CONF_NAME: "Left", CONF_HOST: "fe80::1%eth0", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")
    assert result["data"][CONF_HOST] == "fe80::1"
    assert result["data"][CONF_INTERFACE] == "eth0"


async def test_manual_setup_reports_an_unreachable_device(hass, _custom_integration):
    result = await _run_manual(
        hass,
        DeviceIdentity(error_key="cannot_connect"),
        {CONF_NAME: "Left", CONF_HOST: "fe80::1", CONF_INTERFACE: "eth0", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_manual_setup_of_a_foreign_device_asks_first(hass, _custom_integration):
    """Not blocked - SSC is not Neumann-exclusive - but shown before confirming."""
    result = await _run_manual(
        hass,
        DeviceIdentity(product="Some Speaker", serial="X1", vendor="Other GmbH"),
        {CONF_NAME: "Left", CONF_HOST: "fe80::1", CONF_INTERFACE: "eth0", CONF_PORT: 45},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unsupported"


# --- Active scan -----------------------------------------------------------
#
# The other untested flow path. Written before the step is touched, so they
# describe the behaviour as it stands rather than as it ends up.


async def _run_scan(hass, found, identities):
    """Open the scan step with `found` speakers answering with `identities`."""
    with (
        patch(
            "custom_components.neumann_kh.config_flow.async_scan_for_speakers",
            return_value=found,
        ),
        patch(
            "custom_components.neumann_kh.config_flow._async_identify_all",
            return_value=list(zip(identities, found, strict=True)),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "scan"}
        )


def _speaker(host="fe80::1%2", port=45, name="KH120-SIMULATED._ssc._tcp.local."):
    from custom_components.neumann_kh.discovery import DiscoveredSpeaker

    return DiscoveredSpeaker(mdns_name=name, host=host, port=port)


def _scan_option_labels(result) -> list[str]:
    """The labels the discovery list actually offers."""
    selector = result["data_schema"].schema[_SELECTED_DEVICE]
    return [option["label"] for option in selector.config["options"]]


async def test_scan_lists_what_answered(hass, _custom_integration):
    """Asserting "a form appeared" would pass on an empty list too."""
    result = await _run_scan(hass, [_speaker()], [_GOOD_IDENTITY])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert not result.get("errors")

    labels = _scan_option_labels(result)
    assert any("Search again" in label or "Erneut suchen" in label for label in labels)
    device = [label for label in labels if _GOOD_IDENTITY.serial in label]
    assert device, labels
    assert "KH 120 II" in device[0]
    assert "fe80::1%2" in device[0]


async def test_a_speaker_already_set_up_is_marked_as_such(hass, _custom_integration):
    """Still selectable, but the list has to say it is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=_GOOD_IDENTITY.serial, data={CONF_HOST: "fe80::1"}
    )
    entry.add_to_hass(hass)

    result = await _run_scan(hass, [_speaker()], [_GOOD_IDENTITY])

    device = [
        label for label in _scan_option_labels(result) if _GOOD_IDENTITY.serial in label
    ]
    assert device and ("already connected" in device[0] or "bereits verbunden" in device[0])


async def test_a_foreign_vendor_is_flagged_in_the_list(hass, _custom_integration):
    foreign = DeviceIdentity(product="Some Speaker", serial="X1", vendor="Other GmbH")

    result = await _run_scan(hass, [_speaker()], [foreign])

    device = [label for label in _scan_option_labels(result) if "X1" in label]
    assert device and "Other GmbH" in device[0], device


async def test_the_retry_button_starts_another_scan(hass, _custom_integration):
    """The empty-result form submits back into the scan step."""
    first = await _run_scan(hass, [], [])
    assert first["errors"] == {"base": "no_devices_found"}

    with (
        patch(
            "custom_components.neumann_kh.config_flow.async_scan_for_speakers",
            return_value=[_speaker()],
        ),
        patch(
            "custom_components.neumann_kh.config_flow._async_identify_all",
            return_value=[(_GOOD_IDENTITY, _speaker())],
        ),
    ):
        second = await hass.config_entries.flow.async_configure(first["flow_id"], {})

    assert second["step_id"] == "scan"
    assert not second.get("errors")
    assert any(_GOOD_IDENTITY.serial in label for label in _scan_option_labels(second))


async def test_scan_without_any_answer_offers_a_retry(hass, _custom_integration):
    """A silent candidate is not a device: the list must not offer it."""
    result = await _run_scan(
        hass, [_speaker()], [DeviceIdentity(error_key="cannot_connect")]
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices_found"}


async def test_a_failing_scan_says_so(hass, _custom_integration):
    with patch(
        "custom_components.neumann_kh.config_flow.async_scan_for_speakers",
        side_effect=OSError("no network"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "scan"}
        )

    assert result["errors"] == {"base": "scan_failed"}


async def _pick_and_name(hass, result, name):
    """Select the single discovered device, then submit `name`."""
    with patch("custom_components.neumann_kh.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"selected_device": _GOOD_IDENTITY.serial}
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: name}
        )


async def test_scan_creates_the_entry_from_the_selected_device(hass, _custom_integration):
    listing = await _run_scan(hass, [_speaker()], [_GOOD_IDENTITY])

    result = await _pick_and_name(hass, listing, "Right")

    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")
    assert result["title"] == "Right"
    assert result["data"][CONF_SERIAL] == _GOOD_IDENTITY.serial
    # The scope id travels inside the discovered address, so no separate value.
    assert result["data"][CONF_HOST] == "fe80::1%2"
    assert result["data"][CONF_INTERFACE] == ""


async def test_scan_confirm_needs_a_name(hass, _custom_integration):
    listing = await _run_scan(hass, [_speaker()], [_GOOD_IDENTITY])

    result = await _pick_and_name(hass, listing, "  ")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "name_required"}


async def test_scan_confirm_of_a_foreign_device_asks_first(hass, _custom_integration):
    foreign = DeviceIdentity(product="Some Speaker", serial="X1", vendor="Other GmbH")
    with (
        patch(
            "custom_components.neumann_kh.config_flow.async_scan_for_speakers",
            return_value=[_speaker()],
        ),
        patch(
            "custom_components.neumann_kh.config_flow._async_identify_all",
            return_value=[(foreign, _speaker())],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "scan"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"selected_device": "X1"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Odd one"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unsupported"


async def test_an_expired_discovery_sends_you_back_to_the_scan(hass, _custom_integration):
    """The result can be dropped while the naming form is still open.

    Not reachable by submitting an unknown key - the list is a select with
    fixed options, so Home Assistant rejects that before the step runs. What
    does happen is a rescan clearing the result behind an open form, which is
    what this reproduces.
    """
    listing = await _run_scan(hass, [_speaker()], [_GOOD_IDENTITY])

    result = await hass.config_entries.flow.async_configure(
        listing["flow_id"], {"selected_device": _GOOD_IDENTITY.serial}
    )
    assert result["step_id"] == "scan_confirm"

    flow = hass.config_entries.flow._progress[listing["flow_id"]]
    flow._discovered = {}
    flow._discovery_info = {}

    result = await hass.config_entries.flow.async_configure(
        listing["flow_id"], {CONF_NAME: "Right"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "discovery_expired"}


# The reconfigure step validates its input the same way the manual step does,
# but "the same way" is an analogy, not a proof - these three cases had no test
# of their own.


async def test_reconfigure_rejects_a_non_ipv6_host(hass, _custom_integration):
    entry = _entry(hass)

    result = await _run_reconfigure(hass, entry, _GOOD_IDENTITY, host="192.168.1.5")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_ipv6"}
    assert entry.data[CONF_HOST] == "fe80::1", "a rejected input must not be stored"


async def test_reconfigure_reports_an_unreachable_device(hass, _custom_integration):
    entry = _entry(hass)

    result = await _run_reconfigure(
        hass, entry, DeviceIdentity(error_key="cannot_connect")
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_HOST] == "fe80::1"


async def test_reconfigure_takes_the_scope_id_out_of_the_host(hass, _custom_integration):
    entry = _entry(hass)
    identity = DeviceIdentity(
        product="KH 120 II",
        serial=_EXISTING_SERIAL,
        version="1_7_4",
        vendor="Georg Neumann GmbH",
    )

    result = await _run_reconfigure(
        hass, entry, identity, host="fe80::9%eth5", interface=""
    )

    assert result["type"] is FlowResultType.ABORT, result.get("errors")
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "fe80::9"
    assert entry.data[CONF_INTERFACE] == "eth5"
