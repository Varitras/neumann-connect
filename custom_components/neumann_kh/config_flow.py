"""Config Flow für Neumann KH (SSC).

Reines UI-Setup (kein YAML nötig). Startpunkt ist ein Menü mit zwei Wegen:

- "scan": Aktive mDNS/Zeroconf-Suche im Netzwerk (siehe discovery.py), das
  Ergebnis wird als Auswahlliste angezeigt - kein manuelles Eintippen von
  IP-Adresse/Interface nötig.
- "manual": Klassische manuelle Eingabe (IP-Adresse, Interface-Dropdown,
  Port, Name) - Fallback für Geräte, die die automatische Suche nicht
  findet (z. B. wenn HA mDNS-Multicast nicht empfangen kann).

Für jeden Lautsprecher wird ein eigener Config Entry angelegt (z. B.
"KH 120 II Links", "KH 120 II Rechts", "KH 750 Sub 1", ...).
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

_NO_INTERFACE_VALUE = ""  # "kein Interface angegeben" (z. B. bei fester IPv4-Adresse)
_SELECTED_DEVICE = "selected_device"


async def _async_get_interface_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Ermittelt die auf dem HA-Host bekannten Netzwerk-Interfaces für das Dropdown.

    Nutzt Home Assistants eingebaute network-Komponente (async_get_adapters),
    die auch von anderen Integrationen (z. B. HomeKit, DLNA) zur
    Interface-Auswahl verwendet wird - kein zusätzliches Python-Paket nötig.
    """
    options = [
        selector.SelectOptionDict(
            value=_NO_INTERFACE_VALUE,
            label="(keine Angabe – nur bei fester IPv4-Adresse nötig)",
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
        # Zwischenspeicher für den Scan-Schritt (lebt nur innerhalb dieses Flows)
        self._discovered: dict[str, DiscoveredSpeaker] = {}
        self._discovery_info: dict[str, dict[str, str | None]] = {}

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

    # --- Weg 2: Aktiver mDNS-Scan mit Auswahlliste --------------------------

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        # Zweiter Aufruf: Nutzer hat aus der Liste ein Gerät gewählt und einen
        # Namen vergeben. Erkennbar am vorhandenen "selected_device"-Feld -
        # so lässt sich sauber zwischen "Formular abschicken" und "erneut
        # scannen" (leeres user_input, siehe unten) unterscheiden.
        if user_input is not None and _SELECTED_DEVICE in user_input:
            selected_key = user_input[_SELECTED_DEVICE]
            name = user_input.get(CONF_NAME, "").strip()
            candidate = self._discovered.get(selected_key)
            info = self._discovery_info.get(selected_key)

            if candidate is None or info is None:
                errors["base"] = "discovery_expired"
            elif not name:
                errors["base"] = "name_required"
            else:
                unique_id = info.get("serial") or f"{candidate.host}_{candidate.port}"
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_HOST: candidate.host,
                        # Scope-ID steckt bereits in candidate.host (%<scope>),
                        # eine gesonderte Interface-Angabe ist daher nicht nötig.
                        CONF_INTERFACE: "",
                        CONF_PORT: candidate.port,
                        CONF_MODEL: info.get("product") or "KH DSP",
                        CONF_SERIAL: info.get("serial") or "",
                        CONF_FIRMWARE_VERSION: info.get("version") or "",
                    },
                )

            # Fehler: dieselbe Auswahlliste erneut mit Fehlermeldung anzeigen
            schema = self.add_suggested_values_to_schema(
                self._build_scan_schema(), user_input
            )
            return self.async_show_form(step_id="scan", data_schema=schema, errors=errors)

        # Erster Aufruf ODER Klick auf "Erneut suchen" (leeres user_input):
        # aktiv im Netzwerk nach SSC-Geräten suchen.
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

    def _build_scan_schema(self) -> vol.Schema:
        """Baut das Auswahl-Formular aus den zuletzt gefundenen Geräten (self._discovered)."""
        options = [
            selector.SelectOptionDict(
                value=key,
                label=f"{info.get('product') or 'KH DSP'} – {self._discovered[key].host}"
                + (f" (Serial: {info['serial']})" if info.get("serial") else ""),
            )
            for key, info in self._discovery_info.items()
        ]
        return vol.Schema(
            {
                vol.Required(_SELECTED_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                ),
                vol.Required(CONF_NAME): str,
            }
        )
