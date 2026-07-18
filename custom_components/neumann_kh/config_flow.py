"""Config Flow for Neumann KH (SSC).

Pure UI setup (no YAML needed). The starting point is a menu with two paths:

- "scan": Active mDNS/Zeroconf search on the network (see discovery.py); the
  result is shown as a selection list, followed by a second step for naming
  the device (pre-filled if this device already had a name before - see
  storage.py).
- "manual": Classic manual input (IP address, interface dropdown, port, name)
  - fallback for devices that the automatic search does not find.

A separate config entry is created for each speaker.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any, NamedTuple

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import storage
from .const import (
    CONF_FIRMWARE_VERSION,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_SERIAL,
    CONF_VENDOR,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VENDOR,
    PATH_IDENTITY_VERSION,
    VENDOR_MARKER_NEUMANN,
)
from .discovery import DiscoveredSpeaker, async_scan_for_speakers
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

_NO_INTERFACE_VALUE = ""  # "no interface specified" (e.g. for a global, non-link-local IPv6 address)
_SELECTED_DEVICE = "selected_device"
_RESCAN_VALUE = "__rescan__"


async def _async_get_interface_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Determine the network interfaces known on the HA host for the dropdown."""
    language = hass.config.language or "en"
    no_interface_label = (
        "(keine Angabe – nur bei globaler, nicht Link-Local IPv6-Adresse nötig)"
        if language.startswith("de")
        else "(none – only needed for a global, non-link-local IPv6 address)"
    )
    options = [
        selector.SelectOptionDict(
            value=_NO_INTERFACE_VALUE,
            label=no_interface_label,
        )
    ]
    try:
        adapters = await network.async_get_adapters(hass)
    except Exception:  # noqa: BLE001 - network component should always be present, but stay defensive
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


def _build_manual_schema(interface_options: list[selector.SelectOptionDict]) -> vol.Schema:
    """Build the form schema for manual input, incl. interface dropdown."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
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
    )


def _build_reconfigure_schema(
    interface_options: list[selector.SelectOptionDict],
) -> vol.Schema:
    """Same fields as manual setup, minus the name - renaming is done in HA."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_INTERFACE, default=_NO_INTERFACE_VALUE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=interface_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
        }
    )


def _already_configured_serials(hass: HomeAssistant) -> set[str]:
    """Collect the serial numbers of all already configured speakers."""
    return {
        entry.unique_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.unique_id
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
    except Exception:  # noqa: BLE001 - catch unexpected errors cleanly
        _LOGGER.exception("Unexpected error while testing the connection to %s", host)
        return DeviceIdentity(error_key="unknown")
    else:
        return DeviceIdentity(product=product, serial=serial, version=version, vendor=vendor)
    finally:
        await client.close()


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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="user", menu_options=["scan", "manual"])

    # --- Path 1: Manual input ----------------------------------------------

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            interface = user_input.get(CONF_INTERFACE, "").strip() or None
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            name = user_input[CONF_NAME].strip()

            # Accept inputs like "fe80::1%eth0": split off the scope ID
            # (ipaddress.IPv6Address does not know about scope IDs) and - if the
            # interface field is empty - use it as the interface. An explicitly
            # chosen interface in the dropdown takes precedence.
            if "%" in host:
                host, _, host_scope = host.partition("%")
                host = host.strip()
                if not interface:
                    interface = host_scope.strip() or None

            if not name:
                errors["base"] = "name_required"
            else:
                try:
                    ipaddress.IPv6Address(host)
                except ValueError:
                    errors["base"] = "invalid_ipv6"
                else:
                    if SSCClient._is_link_local(host) and not interface:  # noqa: SLF001
                        errors["base"] = "interface_required_for_link_local"
                    else:
                        identity = await _async_test_connection(host, port, interface)
                        if identity.error_key:
                            errors["base"] = identity.error_key
                        else:
                            unique_id = identity.serial or f"{host}_{port}"
                            await self.async_set_unique_id(str(unique_id))
                            self._abort_if_unique_id_configured()
                            if identity.serial:
                                await storage.async_remember_name(
                                    self.hass, identity.serial, name
                                )

                            entry_data = {
                                CONF_NAME: name,
                                CONF_HOST: host,
                                CONF_INTERFACE: interface or "",
                                CONF_PORT: port,
                                CONF_MODEL: identity.product or "KH DSP",
                                CONF_SERIAL: identity.serial or "",
                                CONF_VENDOR: identity.vendor or "",
                                CONF_FIRMWARE_VERSION: identity.version or "",
                            }
                            if not identity.is_neumann:
                                # Setup is not blocked - the integration talks
                                # plain SSC and stays usable on other vendors'
                                # devices. The user just gets to see what was
                                # actually found before confirming.
                                self._pending_entry = entry_data
                                self._pending_identity = identity
                                return await self.async_step_unsupported()

                            return self.async_create_entry(title=name, data=entry_data)

        interface_options = await _async_get_interface_options(self.hass)
        schema = _build_manual_schema(interface_options)

        # On an error the form is shown again. Without carrying over the values
        # from the last attempt as "suggested_values", HA would show an empty
        # form and the user would have to retype all fields.
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    # --- Reconfigure: change address/interface/port of an existing entry -----

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change the connection details of an existing speaker.

        A link-local address depends on the interface and a speaker can move to
        a different port, so without this the only way to correct either was to
        delete the entry and set it up again - losing its entity IDs, history
        and any automation referencing them.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            interface = user_input.get(CONF_INTERFACE, "").strip() or None
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            if "%" in host:
                host, _, host_scope = host.partition("%")
                host = host.strip()
                if not interface:
                    interface = host_scope.strip() or None

            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                errors["base"] = "invalid_ipv6"
            else:
                if SSCClient._is_link_local(host) and not interface:  # noqa: SLF001
                    errors["base"] = "interface_required_for_link_local"
                else:
                    identity = await _async_test_connection(host, port, interface)
                    if identity.error_key:
                        errors["base"] = identity.error_key
                    else:
                        # Guard against pointing an entry at a different
                        # speaker: that would silently attach one device's
                        # history to another. Entries created without a serial
                        # (unique_id is host_port) cannot be checked this way.
                        # A known serial must be matched. Accepting a device
                        # that reports none would silently attach this entry -
                        # its history and stored exports - to whatever answered
                        # at the new address.
                        known_serial = entry.data.get(CONF_SERIAL)
                        if known_serial and identity.serial != known_serial:
                            return self.async_abort(reason="wrong_device")

                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                CONF_HOST: host,
                                CONF_INTERFACE: interface or "",
                                CONF_PORT: port,
                                CONF_MODEL: identity.product or entry.data.get(CONF_MODEL),
                                CONF_VENDOR: identity.vendor or "",
                                CONF_FIRMWARE_VERSION: identity.version or "",
                            },
                        )

        interface_options = await _async_get_interface_options(self.hass)
        schema = _build_reconfigure_schema(interface_options)
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
            errors=errors,
            description_placeholders={"device": entry.title},
        )

    # --- Shared: confirmation for devices of another vendor ------------------

    async def async_step_unsupported(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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

    # --- Path 2: Active mDNS scan, then naming ------------------------------

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
        except Exception:  # noqa: BLE001 - scan should fail clearly on errors, not crash
            _LOGGER.exception("Unexpected error during the mDNS scan")
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "scan_failed"}
            )

        self._discovered = {}
        self._discovery_info = {}

        for speaker in speakers:
            identity = await _async_test_connection(speaker.host, speaker.port, interface=None)
            if identity.error_key:
                _LOGGER.debug(
                    "Discovered device %s (%s) did not respond to SSC requests: %s",
                    speaker.mdns_name,
                    speaker.host,
                    identity.error_key,
                )
                continue
            key = identity.serial or speaker.mdns_name
            self._discovered[key] = speaker
            self._discovery_info[key] = identity

        if not self._discovered:
            # Empty schema = only a submit button that triggers the scan again.
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "no_devices_found"}
            )

        return self.async_show_form(step_id="scan", data_schema=self._build_scan_schema())

    async def async_step_scan_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Second step: assign a name (pre-filled if the device is known)."""
        errors: dict[str, str] = {}
        candidate = self._discovered.get(self._pending_key or "")
        identity = self._discovery_info.get(self._pending_key or "")

        if candidate is None or identity is None:
            # Discovery result expired (e.g. flow open too long) -> rescan.
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "discovery_expired"}
            )

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["base"] = "name_required"
            else:
                unique_id = identity.serial or f"{candidate.host}_{candidate.port}"
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()
                if identity.serial:
                    await storage.async_remember_name(self.hass, identity.serial, name)

                entry_data = {
                    CONF_NAME: name,
                    CONF_HOST: candidate.host,
                    # Scope ID is already contained in candidate.host (%<scope>).
                    CONF_INTERFACE: "",
                    CONF_PORT: candidate.port,
                    CONF_MODEL: identity.product or "KH DSP",
                    CONF_SERIAL: identity.serial or "",
                    CONF_VENDOR: identity.vendor or "",
                    CONF_FIRMWARE_VERSION: identity.version or "",
                }
                if not identity.is_neumann:
                    self._pending_entry = entry_data
                    self._pending_identity = identity
                    return await self.async_step_unsupported()

                return self.async_create_entry(title=name, data=entry_data)

        remembered_name = None
        if identity.serial:
            remembered_name = await storage.async_get_remembered_name(self.hass, identity.serial)

        schema = vol.Schema({vol.Required(CONF_NAME): str})
        if remembered_name:
            schema = self.add_suggested_values_to_schema(schema, {CONF_NAME: remembered_name})

        return self.async_show_form(
            step_id="scan_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device": f"{identity.product or 'KH DSP'} – {candidate.host}"
            },
        )

    def _build_scan_schema(self) -> vol.Schema:
        """Build the selection form from the most recently discovered devices."""
        de = (self.hass.config.language or "en").startswith("de")
        configured_serials = _already_configured_serials(self.hass)
        options = [
            selector.SelectOptionDict(
                value=_RESCAN_VALUE,
                label="🔄 Erneut suchen" if de else "🔄 Search again",
            )
        ]
        for key, identity in self._discovery_info.items():
            label = f"{identity.product or 'KH DSP'} – {self._discovered[key].host}"
            if identity.serial:
                label += f" (Serial: {identity.serial})"
            if identity.serial in configured_serials:
                label += " — ✓ bereits verbunden" if de else " — ✓ already connected"
            if not identity.is_neumann:
                # Kept selectable on purpose: SSC is not Neumann-exclusive, so
                # the device may still work - the label just says what it is.
                label += (
                    f" — ⚠ kein Neumann-Gerät ({identity.vendor})"
                    if de
                    else f" — ⚠ not a Neumann device ({identity.vendor})"
                )
            options.append(selector.SelectOptionDict(value=key, label=label))

        return vol.Schema(
            {
                vol.Required(_SELECTED_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                ),
            }
        )
