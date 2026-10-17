"""Config Flow for Neumann KH (SSC).

Pure UI setup (no YAML needed). The starting point is a menu with two paths:

- "scan": Active mDNS/Zeroconf search on the network (see discovery.py); the
  result is shown as a selection list, followed by a second step for naming
  the device (pre-filled if this device already had a name before - see
  storage.py).
- "manual": Classic manual input (IP address, interface dropdown, port, name)
  - fallback for devices that the automatic search does not find.

Home Assistant also passes in mDNS announcements on its own (see the
"zeroconf" key in manifest.json), which keeps the stored address correct
without anyone having to notice that it went stale - see async_step_zeroconf.

A separate config entry is created for each speaker.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any, NamedTuple

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import (
    ATTR_PROPERTIES_ID,
    ZeroconfServiceInfo,
)

from . import storage
from ._util import localized
from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    CONF_VENDOR,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    FALLBACK_MODEL,
    MAX_PARALLEL_IDENTITY_QUERIES,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VENDOR,
    PATH_IDENTITY_VERSION,
    VENDOR_MARKER_NEUMANN,
)
from .discovery import DiscoveredSpeaker, async_scan_for_speakers, pick_host
from .identity import as_identity_text, mask_serial, serial_matches
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError, mask_host

_LOGGER = logging.getLogger(__name__)

_NO_INTERFACE_VALUE = (
    ""  # "no interface specified" (e.g. for a global, non-link-local IPv6 address)
)
_SELECTED_DEVICE = "selected_device"
_RESCAN_VALUE = "__rescan__"


async def _async_get_interface_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Determine the network interfaces known on the HA host for the dropdown."""
    no_interface_label = localized(
        hass.config.language,
        "(keine Angabe – nur bei globaler, nicht Link-Local IPv6-Adresse nötig)",
        "(none – only needed for a global, non-link-local IPv6 address)",
    )
    options = [
        selector.SelectOptionDict(
            value=_NO_INTERFACE_VALUE,
            label=no_interface_label,
        )
    ]
    try:
        adapters = await network.async_get_adapters(hass)
    except Exception:
        _LOGGER.debug("Could not determine network interfaces", exc_info=True)
        return options

    for adapter in adapters:
        name = adapter.get("name")
        if not name:
            continue
        addresses = [ip["address"] for ip in adapter.get("ipv6", []) if ip.get("address")]
        addresses += [ip["address"] for ip in adapter.get("ipv4", []) if ip.get("address")]
        label = f"{name} ({', '.join(addresses)})" if addresses else name
        options.append(selector.SelectOptionDict(value=name, label=label))

    return options


def _connection_fields(interface_options: list[selector.SelectOptionDict]) -> dict:
    """Address, interface and port - shared by manual setup and reconfigure."""
    return {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_INTERFACE, default=_NO_INTERFACE_VALUE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=interface_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                custom_value=True,  # allows manual input if the interface is not listed
            )
        ),
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }


def _split_scope_id(host: str, interface: str | None) -> tuple[str, str | None]:
    """Accept "fe80::1%eth0" in the address field and pull the scope apart.

    ipaddress.IPv6Address does not know about scope IDs, so the address has to
    be split before it can be validated. An interface picked in the dropdown
    wins over one typed into the address.
    """
    if "%" not in host:
        return host, interface
    host, _, scope = host.partition("%")
    return host.strip(), interface or (scope.strip() or None)


def _known_serials(hass: HomeAssistant) -> tuple[set[str], set[str]]:
    """Serials of the speakers already set up, and of those the user ignored.

    Ignoring a discovery creates a config entry as well, but nothing is
    connected - the scan list must not call it that.
    """
    connected: set[str] = set()
    ignored: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not entry.unique_id:
            continue
        target = ignored if entry.source == config_entries.SOURCE_IGNORE else connected
        target.add(entry.unique_id)
    return connected, ignored


class _CheckedConnection(NamedTuple):
    """What the address form turned into, and the first problem found, if any."""

    host: str
    interface: str | None
    port: int
    identity: DeviceIdentity | None
    error: str | None


def _entry_data(
    name: str, host: str, interface: str, port: int, serial: str, identity: DeviceIdentity
) -> dict[str, Any]:
    """The data of a new entry - one shape for manual, scan and zeroconf."""
    return {
        CONF_NAME: name,
        CONF_HOST: host,
        CONF_INTERFACE: interface,
        CONF_PORT: port,
        CONF_MODEL: identity.product or FALLBACK_MODEL,
        CONF_SERIAL: serial,
        CONF_VENDOR: identity.vendor or "",
        CONF_FIRMWARE_VERSION: identity.version or "",
    }


class DeviceIdentity(NamedTuple):
    """Result of a connection test: what the device reports about itself."""

    product: str | None = None
    serial: str | None = None
    version: str | None = None
    vendor: str | None = None
    error_key: str | None = None

    @property
    def is_neumann(self) -> bool:
        """Whether the device identifies itself as a Neumann product.

        Both test devices report "Georg Neumann GmbH" as
        device/identity/vendor. A device that does not expose the field at all
        is not treated as foreign - the field is verified on the KH 120 II and
        KH 750 only, so absence is inconclusive rather than a negative.
        """
        if self.vendor is None:
            return True
        return VENDOR_MARKER_NEUMANN in self.vendor.lower()


async def _async_test_connection(host: str, port: int, interface: str | None) -> DeviceIdentity:
    """Test the SSC connection and read out the device identity.

    `error_key` is None on success.
    """
    client = SSCClient(host=host, port=port, interface=interface, timeout=DEFAULT_TIMEOUT)
    try:
        product = await client.get(PATH_IDENTITY_PRODUCT)
        serial = await client.get(PATH_IDENTITY_SERIAL)
        version = await client.get(PATH_IDENTITY_VERSION)
        try:
            vendor = await client.get(PATH_IDENTITY_VENDOR)
        except SSCDeviceError:
            # Verified present on the KH 120 II and KH 750, but not on every
            # model - a rejection here must not fail the whole setup.
            _LOGGER.debug("Device %s does not expose device/identity/vendor", host)
            vendor = None
    except SSCConnectionError:
        return DeviceIdentity(error_key="cannot_connect")
    except SSCTimeoutError:
        return DeviceIdentity(error_key="timeout")
    except SSCDeviceError:
        return DeviceIdentity(error_key="cannot_connect")
    except Exception:
        _LOGGER.exception("Unexpected error while testing the connection to %s", mask_host(host))
        return DeviceIdentity(error_key="unknown")
    else:
        return DeviceIdentity(
            product=as_identity_text(product),
            serial=as_identity_text(serial),
            version=as_identity_text(version),
            vendor=as_identity_text(vendor),
        )
    finally:
        await client.close()


async def _async_check_connection(user_input: dict[str, Any]) -> _CheckedConnection:
    """Validate the address form and ask the device who it is."""
    host, interface = _split_scope_id(
        user_input[CONF_HOST].strip(), user_input.get(CONF_INTERFACE, "").strip() or None
    )
    port = user_input.get(CONF_PORT, DEFAULT_PORT)
    try:
        ipaddress.IPv6Address(host)
    except ValueError:
        return _CheckedConnection(host, interface, port, None, "invalid_ipv6")
    if SSCClient.is_link_local(host) and not interface:
        return _CheckedConnection(host, interface, port, None, "interface_required_for_link_local")
    identity = await _async_test_connection(host, port, interface)
    return _CheckedConnection(host, interface, port, identity, identity.error_key)


async def _async_identify_all(
    speakers: list[DiscoveredSpeaker],
) -> list[tuple[DeviceIdentity, DiscoveredSpeaker]]:
    """Ask every candidate who it is, a few at a time.

    Serially this cost one connection timeout per silent candidate, which adds
    up to minutes on a segment carrying stale announcements - paid by a config
    flow the user is watching, and by the setup repair on every failed retry.
    """
    semaphore = asyncio.Semaphore(MAX_PARALLEL_IDENTITY_QUERIES)

    async def _one(speaker: DiscoveredSpeaker) -> tuple[DeviceIdentity, DiscoveredSpeaker]:
        async with semaphore:
            identity = await _async_test_connection(speaker.host, speaker.port, interface=None)
        return identity, speaker

    return list(await asyncio.gather(*(_one(speaker) for speaker in speakers)))


def _scan_option_label(
    identity: DeviceIdentity,
    host: str,
    known_serials: tuple[set[str], set[str]],
    language: str | None,
) -> str:
    """One line of the discovery list: what was found, and what is notable.

    Building the label is text assembly, not flow control - keeping it out of
    the schema builder leaves that function about the schema.
    """
    connected, ignored = known_serials
    label = f"{identity.product or FALLBACK_MODEL} – {host}"
    if identity.serial:
        label += localized(
            language, f" (Seriennummer: {identity.serial})", f" (Serial: {identity.serial})"
        )
    if identity.serial in connected:
        label += localized(language, " – ✓ bereits verbunden", " – ✓ already connected")
    if identity.serial in ignored:
        label += localized(language, " – ignoriert", " – ignored")
    if not identity.is_neumann:
        # Kept selectable on purpose: SSC is not Neumann-exclusive, so the
        # device may still work - the label just says what it is.
        label += localized(
            language,
            f" – ⚠ kein Neumann-Gerät ({identity.vendor})",
            f" – ⚠ not a Neumann device ({identity.vendor})",
        )
    return label


class NeumannKHConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow, one entry per physical speaker."""

    VERSION = 1

    def __init__(self) -> None:
        # Temporary storage, lives only within this flow.
        self._discovered: dict[str, DiscoveredSpeaker] = {}
        self._discovery_info: dict[str, DeviceIdentity] = {}
        self._pending_key: str | None = None
        self._pending_entry: dict[str, Any] | None = None
        self._pending_identity: DeviceIdentity | None = None

    # --- Entry point: menu with the two paths ------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["scan", "manual"])

    # --- Path 1: Manual input ----------------------------------------------

    async def _show_manual_form(
        self, user_input: dict[str, Any] | None, error: str | None = None
    ) -> ConfigFlowResult:
        """Show the manual form again, optionally with one error.

        The values of the failed attempt are carried over as suggested values -
        without that Home Assistant shows an empty form and every field has to
        be typed again.
        """
        interface_options = await _async_get_interface_options(self.hass)
        schema = vol.Schema({vol.Required(CONF_NAME): str, **_connection_fields(interface_options)})
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors={"base": error} if error else {},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return await self._show_manual_form(None)

        name = user_input[CONF_NAME].strip()
        if not name:
            return await self._show_manual_form(user_input, "name_required")

        checked = await _async_check_connection(user_input)
        if checked.error:
            return await self._show_manual_form(user_input, checked.error)
        identity = checked.identity

        await self.async_set_unique_id(str(identity.serial or f"{checked.host}_{checked.port}"))
        self._abort_if_unique_id_configured()
        if identity.serial:
            await storage.async_remember_name(self.hass, identity.serial, name)

        entry_data = _entry_data(
            name,
            checked.host,
            checked.interface or "",
            checked.port,
            identity.serial or "",
            identity,
        )
        return await self._async_finish(entry_data, identity)

    async def _async_finish(
        self, entry_data: dict[str, Any], identity: DeviceIdentity
    ) -> ConfigFlowResult:
        """Create the entry, or first show what was found if it is not a Neumann.

        Setup is not blocked - the integration talks plain SSC and stays usable
        on other vendors' devices. The user just gets to see what was actually
        found before confirming.
        """
        if not identity.is_neumann:
            self._pending_entry = entry_data
            self._pending_identity = identity
            return await self.async_step_unsupported()
        return self.async_create_entry(title=entry_data[CONF_NAME], data=entry_data)

    # --- Reconfigure: change address/interface/port of an existing entry -----

    async def _show_reconfigure_form(
        self, entry, user_input: dict[str, Any] | None, error: str | None = None
    ) -> ConfigFlowResult:
        """Show the reconfigure form, pre-filled from the attempt or the entry."""
        interface_options = await _async_get_interface_options(self.hass)
        # No name field: renaming is done in Home Assistant itself.
        schema = vol.Schema(_connection_fields(interface_options))
        schema = self.add_suggested_values_to_schema(
            schema,
            user_input
            or {
                CONF_HOST: entry.data.get(CONF_HOST, ""),
                CONF_INTERFACE: entry.data.get(CONF_INTERFACE, _NO_INTERFACE_VALUE),
                CONF_PORT: entry.data.get(CONF_PORT, DEFAULT_PORT),
            },
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors={"base": error} if error else {},
            description_placeholders={"device": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the connection details of an existing speaker.

        A link-local address depends on the interface and a speaker can move to
        a different port, so without this the only way to correct either was to
        delete the entry and set it up again - losing its entity IDs, history
        and any automation referencing them.
        """
        entry = self._get_reconfigure_entry()
        if user_input is None:
            return await self._show_reconfigure_form(entry, None)

        checked = await _async_check_connection(user_input)
        if checked.error:
            return await self._show_reconfigure_form(entry, user_input, checked.error)
        identity = checked.identity

        # Guard against pointing an entry at a different speaker: that would
        # silently attach one device's history to another. Entries created
        # without a serial (unique_id is host_port) cannot be checked this way.
        # A known serial must be matched - accepting a device that reports none
        # would attach this entry, its history and its stored exports, to
        # whatever answered at the new address.
        known_serial = entry.data.get(CONF_SERIAL)
        if known_serial and not serial_matches(known_serial, identity.serial):
            return self.async_abort(reason="wrong_device")

        return self.async_update_reload_and_abort(
            entry,
            data_updates={
                CONF_HOST: checked.host,
                CONF_INTERFACE: checked.interface or "",
                CONF_PORT: checked.port,
                CONF_MODEL: identity.product or entry.data.get(CONF_MODEL),
                CONF_VENDOR: identity.vendor or "",
                CONF_FIRMWARE_VERSION: identity.version or "",
            },
        )

    # --- Shared: confirmation for devices of another vendor ------------------

    async def async_step_unsupported(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn about a device that does not identify as Neumann, then proceed.

        The SSC protocol is not exclusive to Neumann, so such a device may well
        work - only the model-specific parts (subwoofer entities, EQ layout)
        are guesses. Setup therefore continues on confirmation instead of being
        rejected.
        """
        if self._pending_entry is None or self._pending_identity is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            return self.async_create_entry(
                title=self._pending_entry[CONF_NAME], data=self._pending_entry
            )

        return self.async_show_form(
            step_id="unsupported",
            data_schema=vol.Schema({}),
            description_placeholders={
                "product": self._pending_identity.product or "?",
                "vendor": self._pending_identity.vendor or "?",
            },
        )

    # --- Passive: mDNS announcement handed in by Home Assistant --------------

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Keep a known speaker's address current, or offer an unknown one.

        A global IPv6 address is built from the prefix the ISP delegates and
        dies with the next forced reconnect; the entry then fails to set up
        until someone reconfigures it by hand. The announcement carries a
        serial number in its TXT record, which is what this integration uses
        as the unique ID, so it tells us which entry an announcement is about.

        The announcement selects the entry; the device at the announced
        address then has to report that same serial before anything is
        written. An announcement that changes nothing costs no contact at all,
        which is the common case by far.

        That check catches a stale or plain wrong record, not a deliberate
        one. The same host controls both the unauthenticated announcement and
        an unauthenticated SSC server, so it can simply repeat the serial it
        claimed. Nothing here can close that: SSC offers no authentication at
        all, and anyone able to run it on the segment can already talk to the
        real speaker directly.
        """
        serial = discovery_info.properties.get(ATTR_PROPERTIES_ID)
        if not serial:
            # Without the serial there is no safe way to tell which entry this
            # belongs to, and guessing by address is what got us here.
            return self.async_abort(reason="no_serial")

        host = pick_host(discovery_info.addresses)
        if host is None:
            return self.async_abort(reason="no_ipv6")

        port = discovery_info.port or DEFAULT_PORT
        updates: dict[str, Any] = {CONF_HOST: host, CONF_PORT: port}
        if "%" in host:
            # The scope ID travels inside the address, so a separately stored
            # interface would be dead weight - and a stale one is misleading.
            updates[CONF_INTERFACE] = _NO_INTERFACE_VALUE

        await self.async_set_unique_id(str(serial))

        known = next(
            (
                entry
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.unique_id == str(serial)
            ),
            None,
        )
        if known is not None and all(
            known.data.get(key) == value for key, value in updates.items()
        ):
            # Nothing would change - the overwhelmingly common case. Leave
            # without touching the network.
            return self.async_abort(reason="already_configured")

        identity = await _async_test_connection(host, port, interface=None)
        if identity.error_key:
            return self.async_abort(reason="cannot_connect")

        if known is not None:
            # Repointing an entry moves its history and its stored backups to
            # whatever answers there, so the device has to confirm who it is.
            if not serial_matches(serial, identity.serial):
                # Masked: shared logs are a common support attachment, and both
                # a serial and a link-local address name specific hardware. What
                # is left of the address still tells two announcements apart.
                _LOGGER.warning(
                    "Ignoring an announcement for %s: %s answered with serial %s",
                    mask_serial(serial),
                    mask_host(host),
                    mask_serial(identity.serial),
                )
                return self.async_abort(reason="wrong_device")
            self._abort_if_unique_id_configured(updates=updates)

        if not identity.serial:
            # Nothing to anchor the entry on. Keeping the announced serial
            # would make an unauthenticated record the device's identity, and
            # a forged one could then occupy a serial the real speaker needs
            # later. Manual setup and the scan do accept such a device: there
            # the user picked it on purpose, here only a broadcast vouches.
            _LOGGER.debug(
                "Ignoring the announcement for %s: %s reports no serial number",
                mask_serial(serial),
                host,
            )
            return self.async_abort(reason="no_serial")

        if not serial_matches(serial, identity.serial):
            # Unknown speaker whose announcement disagrees with the device.
            # The device is the authority, so anchor on what it reports -
            # otherwise the entry would carry one serial as its unique ID and
            # another in its data.
            await self.async_set_unique_id(str(identity.serial))
            self._abort_if_unique_id_configured(updates=updates)

        self._pending_identity = identity
        # The serial is whatever ended up as the unique ID above, so the two
        # cannot drift.
        self._pending_entry = _entry_data(
            "", host, _NO_INTERFACE_VALUE, port, str(self.unique_id or ""), identity
        )
        # Shown on the discovery card in the integrations panel.
        self.context["title_placeholders"] = {
            "name": f"{identity.product or FALLBACK_MODEL} ({self.unique_id})"
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name a speaker that mDNS turned up and that is not configured yet."""
        errors: dict[str, str] = {}
        entry_data = self._pending_entry
        identity = self._pending_identity
        if entry_data is None or identity is None:
            return self.async_abort(reason="discovery_expired")

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["base"] = "name_required"
            else:
                entry_data = {**entry_data, CONF_NAME: name}
                if identity.serial:
                    await storage.async_remember_name(self.hass, identity.serial, name)
                return await self._async_finish(entry_data, identity)

        suggested = None
        if identity.serial:
            suggested = await storage.async_get_remembered_name(self.hass, identity.serial)

        schema = vol.Schema({vol.Required(CONF_NAME): str})
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, {CONF_NAME: suggested})

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device": f"{identity.product or FALLBACK_MODEL} – {entry_data[CONF_HOST]}"
            },
        )

    # --- Path 2: Active mDNS scan, then naming ------------------------------

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # User selected something from the list.
        if user_input is not None and _SELECTED_DEVICE in user_input:
            selected_key = user_input[_SELECTED_DEVICE]
            if selected_key != _RESCAN_VALUE:
                self._pending_key = selected_key
                return await self.async_step_scan_confirm()
            # "Search again" selected -> fall through to a normal rescan below.

        # First call, click on "Search again", or return from an expired
        # discovery result: actively search the network.
        try:
            speakers = await async_scan_for_speakers(self.hass)
        except Exception:
            _LOGGER.exception("Unexpected error during the mDNS scan")
            return self._rescan_form("scan_failed")

        self._discovered = {}
        self._discovery_info = {}

        # Identified concurrently, a few at a time. One after another this cost
        # the connection timeout per silent candidate, so a segment with a
        # handful of stale records left the user staring at a spinner for
        # minutes. The cap keeps it from opening dozens of sockets at once.
        for identity, speaker in await _async_identify_all(speakers):
            if identity.error_key:
                _LOGGER.debug(
                    "Discovered device at %s did not respond to SSC requests: %s",
                    speaker.host,
                    identity.error_key,
                )
                continue
            key = identity.serial or speaker.mdns_name
            self._discovered[key] = speaker
            self._discovery_info[key] = identity

        if not self._discovered:
            # Empty schema = only a submit button that triggers the scan again.
            return self._rescan_form("no_devices_found")

        return self.async_show_form(step_id="scan", data_schema=self._build_scan_schema())

    async def _show_scan_confirm_form(
        self, identity: DeviceIdentity, candidate: DiscoveredSpeaker, error: str | None
    ) -> ConfigFlowResult:
        """Ask for a name, pre-filled if this speaker carried one before."""
        remembered_name = None
        if identity.serial:
            remembered_name = await storage.async_get_remembered_name(self.hass, identity.serial)

        schema = vol.Schema({vol.Required(CONF_NAME): str})
        if remembered_name:
            schema = self.add_suggested_values_to_schema(schema, {CONF_NAME: remembered_name})

        return self.async_show_form(
            step_id="scan_confirm",
            data_schema=schema,
            errors={"base": error} if error else {},
            description_placeholders={
                "device": f"{identity.product or FALLBACK_MODEL} – {candidate.host}"
            },
        )

    def _rescan_form(self, error: str) -> ConfigFlowResult:
        """Empty schema: a single button that starts the search over."""
        return self.async_show_form(
            step_id="scan", data_schema=vol.Schema({}), errors={"base": error}
        )

    async def async_step_scan_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Second step: assign a name (pre-filled if the device is known)."""
        candidate = self._discovered.get(self._pending_key or "")
        identity = self._discovery_info.get(self._pending_key or "")
        if candidate is None or identity is None:
            # Discovery result expired (e.g. flow open too long) -> rescan.
            return self._rescan_form("discovery_expired")

        if user_input is None:
            return await self._show_scan_confirm_form(identity, candidate, None)

        name = user_input.get(CONF_NAME, "").strip()
        if not name:
            return await self._show_scan_confirm_form(identity, candidate, "name_required")

        unique_id = identity.serial or f"{candidate.host}_{candidate.port}"
        await self.async_set_unique_id(str(unique_id))
        self._abort_if_unique_id_configured()
        if identity.serial:
            await storage.async_remember_name(self.hass, identity.serial, name)

        # No interface: the scope ID is already part of candidate.host (%<scope>).
        entry_data = _entry_data(
            name, candidate.host, "", candidate.port, identity.serial or "", identity
        )
        return await self._async_finish(entry_data, identity)

    def _build_scan_schema(self) -> vol.Schema:
        """Build the selection form from the most recently discovered devices."""
        language = self.hass.config.language
        known_serials = _known_serials(self.hass)
        options = [
            selector.SelectOptionDict(
                value=_RESCAN_VALUE,
                label=localized(language, "🔄 Erneut suchen", "🔄 Search again"),
            )
        ]
        options += [
            selector.SelectOptionDict(
                value=key,
                label=_scan_option_label(
                    identity, self._discovered[key].host, known_serials, language
                ),
            )
            for key, identity in self._discovery_info.items()
        ]

        return vol.Schema(
            {
                vol.Required(_SELECTED_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                ),
            }
        )
