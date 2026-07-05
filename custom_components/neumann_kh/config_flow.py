"""Config Flow für Neumann KH (SSC).

Reines UI-Setup (kein YAML nötig). Startpunkt ist ein Menü mit zwei Wegen:

- "scan": Aktive mDNS/Zeroconf-Suche im Netzwerk (siehe discovery.py), das
  Ergebnis wird als Auswahlliste angezeigt, danach ein zweiter Schritt zur
  Namensvergabe (vorausgefüllt, falls dieses Gerät schon einmal einen Namen
  hatte - siehe storage.py).
- "manual": Klassische manuelle Eingabe (IP-Adresse, Interface-Dropdown,
  Port, Name) - Fallback für Geräte, die die automatische Suche nicht findet.

Für jeden Lautsprecher wird ein eigener Config Entry angelegt.
"""

from __future__ import annotations

import logging
from typing import Any

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
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VERSION,
)
from .discovery import DiscoveredSpeaker, async_scan_for_speakers
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

_NO_INTERFACE_VALUE = ""  # "kein Interface angegeben" (z. B. bei globaler, nicht Link-Local IPv6-Adresse)
_SELECTED_DEVICE = "selected_device"
_RESCAN_VALUE = "__rescan__"


async def _async_get_interface_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Ermittelt die auf dem HA-Host bekannten Netzwerk-Interfaces für das Dropdown."""
    options = [
        selector.SelectOptionDict(
            value=_NO_INTERFACE_VALUE,
            label="(keine Angabe – nur bei globaler, nicht Link-Local IPv6-Adresse nötig)",
        )
    ]
    try:
        adapters = await network.async_get_adapters(hass)
    except Exception:  # noqa: BLE001 - Netzwerk-Komponente sollte immer da sein, aber defensiv bleiben
        _LOGGER.debug("Netzwerk-Interfaces konnten nicht ermittelt werden", exc_info=True)
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
    """Baut das Formular-Schema für die manuelle Eingabe, inkl. Interface-Dropdown."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_INTERFACE, default=_NO_INTERFACE_VALUE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=interface_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,  # erlaubt manuelle Eingabe, falls Interface nicht gelistet ist
                )
            ),
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        }
    )


def _already_configured_serials(hass: HomeAssistant) -> set[str]:
    """Sammelt die Seriennummern aller bereits eingerichteten Lautsprecher."""
    return {
        entry.unique_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.unique_id
    }


async def _async_test_connection(
    host: str, port: int, interface: str | None
) -> tuple[str | None, str | None, str | None, str | None]:
    """Testet die SSC-Verbindung und liest Modell + Seriennummer + Firmware-Version aus.

    Rückgabe: (product, serial, firmware_version, error_key). error_key ist
    None bei Erfolg.
    """
    client = SSCClient(host=host, port=port, interface=interface, timeout=DEFAULT_TIMEOUT)
    try:
        product = await client.get(PATH_IDENTITY_PRODUCT)
        serial = await client.get(PATH_IDENTITY_SERIAL)
        version = await client.get(PATH_IDENTITY_VERSION)
    except SSCConnectionError:
        return None, None, None, "cannot_connect"
    except SSCTimeoutError:
        return None, None, None, "timeout"
    except SSCDeviceError:
        return None, None, None, "cannot_connect"
    except Exception:  # noqa: BLE001 - unerwartete Fehler sauber abfangen
        _LOGGER.exception("Unerwarteter Fehler beim Verbindungstest zu %s", host)
        return None, None, None, "unknown"
    else:
        return product, serial, version, None
    finally:
        await client.close()


class NeumannKHConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow, ein Entry pro physischem Lautsprecher."""

    VERSION = 1

    def __init__(self) -> None:
        # Zwischenspeicher, lebt nur innerhalb dieses Flows.
        self._discovered: dict[str, DiscoveredSpeaker] = {}
        self._discovery_info: dict[str, dict[str, str | None]] = {}
        self._pending_key: str | None = None

    # --- Einstiegspunkt: Menü mit den beiden Wegen -------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="user", menu_options=["scan", "manual"])

    # --- Weg 1: Manuelle Eingabe -------------------------------------------

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            interface = user_input.get(CONF_INTERFACE, "").strip() or None
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            name = user_input[CONF_NAME].strip()

            if not name:
                errors["base"] = "name_required"
            elif host.lower().startswith("fe80") and not interface:
                errors["base"] = "interface_required_for_link_local"
            else:
                product, serial, version, error_key = await _async_test_connection(
                    host, port, interface
                )
                if error_key:
                    errors["base"] = error_key
                else:
                    unique_id = serial or f"{host}_{port}"
                    await self.async_set_unique_id(str(unique_id))
                    self._abort_if_unique_id_configured()
                    if serial:
                        await storage.async_remember_name(self.hass, serial, name)

                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_NAME: name,
                            CONF_HOST: host,
                            CONF_INTERFACE: interface or "",
                            CONF_PORT: port,
                            CONF_MODEL: product or "KH DSP",
                            CONF_SERIAL: serial or "",
                            CONF_FIRMWARE_VERSION: version or "",
                        },
                    )

        interface_options = await _async_get_interface_options(self.hass)
        schema = _build_manual_schema(interface_options)

        # Bei einem Fehler wird das Formular erneut angezeigt. Ohne die Werte aus
        # dem letzten Versuch als "suggested_values" zu übernehmen, würde HA ein
        # leeres Formular zeigen und der Nutzer müsste alle Felder neu eintippen.
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    # --- Weg 2: Aktiver mDNS-Scan, danach Namensvergabe ---------------------

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # Nutzer hat aus der Liste etwas gewählt.
        if user_input is not None and _SELECTED_DEVICE in user_input:
            selected_key = user_input[_SELECTED_DEVICE]
            if selected_key != _RESCAN_VALUE:
                self._pending_key = selected_key
                return await self.async_step_scan_confirm()
            # "Erneut suchen" gewählt -> unten normal neu scannen.

        # Erster Aufruf, Klick auf "Erneut suchen", oder Rücksprung von einem
        # abgelaufenen Discovery-Ergebnis: aktiv im Netzwerk suchen.
        try:
            speakers = await async_scan_for_speakers(self.hass)
        except Exception:  # noqa: BLE001 - Scan soll bei Fehlern klar scheitern, nicht crashen
            _LOGGER.exception("Unerwarteter Fehler beim mDNS-Scan")
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "scan_failed"}
            )

        self._discovered = {}
        self._discovery_info = {}

        for speaker in speakers:
            product, serial, version, error_key = await _async_test_connection(
                speaker.host, speaker.port, interface=None
            )
            if error_key:
                _LOGGER.debug(
                    "Gefundenes Gerät %s (%s) antwortete nicht auf SSC-Anfragen: %s",
                    speaker.mdns_name,
                    speaker.host,
                    error_key,
                )
                continue
            key = serial or speaker.mdns_name
            self._discovered[key] = speaker
            self._discovery_info[key] = {"product": product, "serial": serial, "version": version}

        if not self._discovered:
            # Leeres Schema = nur ein Absenden-Button, der den Scan erneut auslöst.
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "no_devices_found"}
            )

        return self.async_show_form(step_id="scan", data_schema=self._build_scan_schema())

    async def async_step_scan_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Zweiter Schritt: Name vergeben (vorausgefüllt, falls Gerät bekannt)."""
        errors: dict[str, str] = {}
        candidate = self._discovered.get(self._pending_key or "")
        info = self._discovery_info.get(self._pending_key or "")

        if candidate is None or info is None:
            # Discovery-Ergebnis abgelaufen (z. B. Flow zu lange offen) -> neu scannen.
            return self.async_show_form(
                step_id="scan", data_schema=vol.Schema({}), errors={"base": "discovery_expired"}
            )

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["base"] = "name_required"
            else:
                unique_id = info.get("serial") or f"{candidate.host}_{candidate.port}"
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()
                if info.get("serial"):
                    await storage.async_remember_name(self.hass, info["serial"], name)

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_HOST: candidate.host,
                        # Scope-ID steckt bereits in candidate.host (%<scope>).
                        CONF_INTERFACE: "",
                        CONF_PORT: candidate.port,
                        CONF_MODEL: info.get("product") or "KH DSP",
                        CONF_SERIAL: info.get("serial") or "",
                        CONF_FIRMWARE_VERSION: info.get("version") or "",
                    },
                )

        remembered_name = None
        if info.get("serial"):
            remembered_name = await storage.async_get_remembered_name(self.hass, info["serial"])

        schema = vol.Schema({vol.Required(CONF_NAME): str})
        if remembered_name:
            schema = self.add_suggested_values_to_schema(schema, {CONF_NAME: remembered_name})

        return self.async_show_form(
            step_id="scan_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device": f"{info.get('product') or 'KH DSP'} – {candidate.host}"
            },
        )

    def _build_scan_schema(self) -> vol.Schema:
        """Baut das Auswahl-Formular aus den zuletzt gefundenen Geräten."""
        configured_serials = _already_configured_serials(self.hass)
        options = [
            selector.SelectOptionDict(value=_RESCAN_VALUE, label="🔄 Erneut suchen")
        ]
        for key, info in self._discovery_info.items():
            label = f"{info.get('product') or 'KH DSP'} – {self._discovered[key].host}"
            if info.get("serial"):
                label += f" (Serial: {info['serial']})"
            if info.get("serial") in configured_serials:
                label += " — ✓ bereits verbunden"
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
