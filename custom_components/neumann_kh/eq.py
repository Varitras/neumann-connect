"""EQ-Entities: pro Band ein Ein/Aus-Schalter, pro EQ-Container ein
"Auf Standard zurücksetzen"-Button (setzt Gain und Boost aller Bänder auf
0 dB, lässt Frequenz/Q/Typ/Enabled unverändert).

Eine volle 1:1-Abbildung aller EQ-Parameter (Typ/Frequenz/Gain/Boost/Q/
Enabled je Band) wäre bei der KH 750 (Hauptausgang + out1 + out2, je bis zu
drei EQ-Container) ca. 800 Entities - nicht mehr überschaubar. Deshalb
bewusst reduziert auf die zwei praktisch wichtigsten Aktionen.

SSC-Arrays lassen sich teilweise schreiben: nicht gewünschte Indizes werden
als `null` übergeben und bleiben unverändert, nur der Ziel-Index ändert sich.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .eq_containers import EQContainer, eq_containers_for_model
from .ssc_client import SSCDeviceError

# --- Band-Ein/Aus-Schalter --------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class NeumannKHEQBandSwitchDescription(SwitchEntityDescription):
    container: EQContainer | None = None
    band_index: int = 0


def build_eq_switch_descriptions(model: str | None) -> list[NeumannKHEQBandSwitchDescription]:
    """Baut eine Switch-Beschreibung pro Band aller passenden EQ-Container."""
    descriptions = []
    for container in eq_containers_for_model(model):
        path_key = "_".join(container.path)
        for band_index in range(container.band_count):
            descriptions.append(
                NeumannKHEQBandSwitchDescription(
                    key=f"{path_key}_band{band_index}_enabled",
                    translation_key="eq_band_enabled",
                    icon="mdi:equalizer",
                    entity_category=EntityCategory.CONFIG,
                    entity_registry_enabled_default=False,  # kann den Klang direkt beeinflussen
                    container=container,
                    band_index=band_index,
                )
            )
    return descriptions


class NeumannKHEQBandSwitch(NeumannKHEntity, SwitchEntity):
    """Schaltet ein einzelnes Band eines EQ-Containers ein/aus (Array-Teilschreiben)."""

    entity_description: NeumannKHEQBandSwitchDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHEQBandSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"
        self._path = description.container.path + ("enabled",)

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {
            "container": self.entity_description.container.label,
            "band": str(self.entity_description.band_index + 1),
        }

    @property
    def is_on(self) -> bool | None:
        values = self.coordinator.value(self._path)
        if not isinstance(values, list) or self.entity_description.band_index >= len(values):
            return None
        return bool(values[self.entity_description.band_index])

    async def _async_set(self, value: bool) -> None:
        array: list[Any] = [None] * self.entity_description.container.band_count
        array[self.entity_description.band_index] = value
        try:
            confirmed = await self.coordinator.client.set(self._path, array)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt: {err}"
            ) from err
        await self._apply_confirmed_value(self._path, confirmed)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)


# --- Reset-auf-Standard-Button ----------------------------------------------


def build_eq_reset_buttons(
    coordinator: NeumannKHCoordinator, entry: ConfigEntry, model: str | None
) -> list["NeumannKHEQResetButton"]:
    """Baut einen Reset-Button pro passendem EQ-Container."""
    return [
        NeumannKHEQResetButton(coordinator, entry, container)
        for container in eq_containers_for_model(model)
    ]


class NeumannKHEQResetButton(NeumannKHEntity, ButtonEntity):
    """Setzt Gain und Boost aller Bänder eines EQ-Containers auf 0 dB zurück."""

    def __init__(
        self, coordinator: NeumannKHCoordinator, entry: ConfigEntry, container: EQContainer
    ) -> None:
        super().__init__(coordinator, entry)
        self._container = container
        path_key = "_".join(container.path)
        self.entity_description = ButtonEntityDescription(
            key=f"{path_key}_reset",
            translation_key="eq_reset",
            icon="mdi:equalizer-outline",
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,  # verändert den Klang direkt
        )
        self._attr_unique_id = f"{self._unique_id_base}_{path_key}_reset"

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"container": self._container.label}

    async def async_press(self) -> None:
        zero = [0.0] * self._container.band_count
        try:
            await self.coordinator.client.set(self._container.path + ("gain",), zero)
            await self.coordinator.client.set(self._container.path + ("boost",), zero)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat den EQ-Reset abgelehnt: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
