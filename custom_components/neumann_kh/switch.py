"""Switch-Entities: Mute, Phasenumkehr (nur Nicht-Subwoofer), Gerät identifizieren.

Per echtem Hardware-Test (khtool-Dump einer KH 120 II, Firmware 1_7_3)
korrigiert:
- "solo" existiert im vollständigen Geräte-Dump NICHT und wurde entfernt.
- Es gibt nur EINE Phasenumkehr für den gesamten (Haupt-)Ausgang
  ("audio/out/phaseinversion"), keine getrennte Ein-/Ausgangs-Phasenumkehr.
  Existiert laut khtools Metadaten NUR bei Nicht-Subwoofer-Modellen (KH 750
  hat stattdessen "subwoofer_phase_inversion", siehe select.py).

"Gerät identifizieren" (device/identification/visual) ist als SCHALTER
umgesetzt, nicht als Auto-Stopp-Button: Ein echter Hardware-Test hat
gezeigt, dass das Blinken zwar von selbst aufhört, aber erst nach mehreren
Minuten (nicht ~10 Sekunden, wie die allgemeine SSC-Doku für andere
Sennheiser-Geräte vermuten ließ) - ein An/Aus-Schalter gibt die Kontrolle
darüber zurück an den Nutzer.

"Auto-Standby" (device/standby/enabled) ist bewusst KEIN Schalter mehr: Per
zwei unabhängigen echten Hardware-Tests bestätigt nicht schreibbar (Fehler
405 "method not allowed" bzw. 400 "message not understood" bei einem
alternativen Pfad) - siehe binary_sensor.py für die nur lesende Variante.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODEL,
    DOMAIN,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_IDENTIFY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSwitchDescription(SwitchEntityDescription):
    """Beschreibung einer Switch-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


# Immer angelegt (modellunabhängig)
COMMON_SWITCH_DESCRIPTIONS: tuple[NeumannKHSwitchDescription, ...] = (
    NeumannKHSwitchDescription(
        key="mute",
        translation_key="mute",
        icon="mdi:volume-mute",
        ssc_path=PATH_OUTPUT_MUTE,
    ),
    NeumannKHSwitchDescription(
        key="identify",
        translation_key="identify",
        icon="mdi:led-on",
        ssc_path=PATH_IDENTIFY,
    ),
)

# Nur bei Nicht-Subwoofer-Modellen (existiert laut khtool-Metadaten nur dort)
PHASE_INVERT_DESCRIPTION = NeumannKHSwitchDescription(
    key="phase_invert",
    translation_key="phase_invert",
    icon="mdi:sine-wave",
    ssc_path=PATH_OUTPUT_PHASE_INVERSION,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Switch-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(COMMON_SWITCH_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) not in MODELS_WITH_SUBWOOFER_FEATURES:
        descriptions.append(PHASE_INVERT_DESCRIPTION)

    async_add_entities(
        NeumannKHSwitch(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSwitch(NeumannKHEntity, SwitchEntity):
    """Boolescher SSC-Wert als Switch."""

    entity_description: NeumannKHSwitchDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return bool(value)

    async def _async_set(self, value: bool) -> None:
        """Setzt den Wert; wandelt eine Geräte-Ablehnung in eine klare HA-Fehlermeldung um."""
        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
