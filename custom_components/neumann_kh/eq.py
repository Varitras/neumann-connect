"""EQ-Entities: ein Ein/Aus-Schalter pro EQ-Container (alle Bänder gemeinsam)
sowie ein "Auf neutral zurücksetzen"-Button pro Container (Gain/Boost aller
Bänder auf 0 dB, Frequenz/Q/Typ bleiben unverändert). Beide standardmäßig
aktiviert, mit `entity_category: config` in der Konfiguration-Sektion.

Eine vollständige 1:1-Abbildung aller EQ-Parameter je Band wäre bei der
KH 750 ca. 800 Entities - nicht mehr überschaubar. Deshalb bewusst auf
Container-Ebene reduziert: ein Schalter schreibt "enabled" für ALLE Bänder
des Containers gleichzeitig, statt jedes Band einzeln. Alle Container-Namen
beginnen bewusst mit "EQ", damit sie in der Konfiguration-Sektion
alphabetisch zusammen gruppiert erscheinen.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .eq_containers import EQContainer, eq_containers_for_model
from .ssc_client import SSCDeviceError

# --- Container-Ein/Aus-Schalter ----------------------------------------------


def build_eq_switches(
    coordinator: NeumannKHCoordinator, entry: ConfigEntry, model: str | None
) -> list["NeumannKHEQContainerSwitch"]:
    """Baut einen Ein/Aus-Schalter pro passendem EQ-Container."""
    return [
        NeumannKHEQContainerSwitch(coordinator, entry, container)
        for container in eq_containers_for_model(model)
    ]


class NeumannKHEQContainerSwitch(NeumannKHEntity, SwitchEntity):
    """Schaltet alle Bänder eines EQ-Containers gemeinsam ein/aus.

    is_on ist True, sobald mindestens ein Band aktiv ist (Ausgangszustand
    kann pro Band unterschiedlich sein, z. B. nach externer Änderung über
    MA1) - der Schalter selbst setzt beim Betätigen immer ALLE Bänder auf
    denselben Wert.
    """

    def __init__(
        self, coordinator: NeumannKHCoordinator, entry: ConfigEntry, container: EQContainer
    ) -> None:
        super().__init__(coordinator, entry)
        self._container = container
        path_key = "_".join(container.path)
        self.entity_description = SwitchEntityDescription(
            key=f"{path_key}_enabled",
            translation_key="eq_enabled",
            icon="mdi:equalizer",
            entity_category=EntityCategory.CONFIG,
        )
        self._attr_unique_id = f"{self._unique_id_base}_{path_key}_enabled"
        self._path = container.path + ("enabled",)

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"container": self._container.label}

    @property
    def is_on(self) -> bool | None:
        values = self.coordinator.value(self._path)
        if not isinstance(values, list) or not values:
            return None
        return any(bool(v) for v in values)

    async def _async_set(self, value: bool) -> None:
        array = [value] * self._container.band_count
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


# --- Reset-auf-neutral-Button ------------------------------------------------


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
