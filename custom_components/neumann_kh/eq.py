"""EQ entities: one on/off switch per EQ container (all bands together) plus a
"reset to flat" button per container (gain/boost of all bands to 0 dB;
frequency/Q/type stay unchanged). Both enabled by default, with
`entity_category: config` in the configuration section.

A full 1:1 mapping of every EQ parameter per band would be about 800 entities
on the KH 750 - no longer manageable. Therefore deliberately reduced to the
container level: one switch writes "enabled" for ALL bands of the container at
once, instead of each band individually. All container names deliberately
begin with "EQ" so they appear grouped together alphabetically in the
configuration section.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .eq_containers import EQContainer, eq_containers_for_model
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

# --- Container on/off switch -------------------------------------------------


def build_eq_switches(
    coordinator: NeumannKHCoordinator, entry: ConfigEntry, model: str | None
) -> list["NeumannKHEQContainerSwitch"]:
    """Builds one on/off switch per matching EQ container."""
    return [
        NeumannKHEQContainerSwitch(coordinator, entry, container)
        for container in eq_containers_for_model(model)
    ]


class NeumannKHEQContainerSwitch(NeumannKHEntity, SwitchEntity):
    """Switches all bands of an EQ container on/off together.

    is_on is True as soon as at least one band is active (the initial state
    can differ per band, e.g. after an external change via MA1) - the switch
    itself always sets ALL bands to the same value when operated.
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
        return {"container": self._container.label_for(self.hass.config.language)}

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
                translation_domain=DOMAIN,
                translation_key="change_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._apply_confirmed_value(self._path, confirmed)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)


# --- Reset-to-flat button ----------------------------------------------------


def build_eq_reset_buttons(
    coordinator: NeumannKHCoordinator, entry: ConfigEntry, model: str | None
) -> list["NeumannKHEQResetButton"]:
    """Builds one reset button per matching EQ container."""
    return [
        NeumannKHEQResetButton(coordinator, entry, container)
        for container in eq_containers_for_model(model)
    ]


class NeumannKHEQResetButton(NeumannKHEntity, ButtonEntity):
    """Resets gain and boost of all bands of an EQ container to 0 dB."""

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
        return {"container": self._container.label_for(self.hass.config.language)}

    async def async_press(self) -> None:
        zero = [0.0] * self._container.band_count
        try:
            await self.coordinator.client.set(self._container.path + ("gain",), zero)
            await self.coordinator.client.set(self._container.path + ("boost",), zero)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="eq_reset_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
