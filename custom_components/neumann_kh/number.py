"""Number-Entities: Level, Dimm, Delay, Logo-Helligkeit, Auto-Standby-Werte
sowie (nur bei erkanntem Subwoofer) die Ausgänge out1/out2.

"Dimm" auf der KH 120 II nicht vorhanden - Entity bleibt bestehen (andere
Modelle), zeigt dort "unbekannt".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONF_MODEL,
    DELAY_MAX_DEFAULT,
    DELAY_MAX_SUBWOOFER,
    DELAY_MIN,
    DIMM_MAX,
    DIMM_MIN,
    DOMAIN,
    LEVEL_MAX,
    LEVEL_MIN,
    MODELS_WITH_LOGO_AND_SAVE,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_LOGO_BRIGHTNESS,
    PATH_OUT1_DELAY,
    PATH_OUT1_LEVEL,
    PATH_OUT2_DELAY,
    PATH_OUT2_LEVEL,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_LEVEL,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    STANDBY_AUTO_TIME_MAX,
    STANDBY_AUTO_TIME_MIN,
    STANDBY_LEVEL_MAX,
    STANDBY_LEVEL_MIN,
    STANDBY_LEVEL_UNIT,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class NeumannKHNumberDescription(NumberEntityDescription):
    """Beschreibung einer Number-Entity inkl. SSC-Pfad.

    integer: Ob beim Schreiben nach int() statt float() konvertiert werden
    soll (z. B. Delay-Werte in Samples).
    """

    ssc_path: tuple[str, ...] = ()
    integer: bool = False


COMMON_NUMBER_DESCRIPTIONS: tuple[NeumannKHNumberDescription, ...] = (
    NeumannKHNumberDescription(
        key="output_level",
        translation_key="output_level",
        icon="mdi:volume-high",
        native_min_value=LEVEL_MIN,
        native_max_value=LEVEL_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        ssc_path=PATH_OUTPUT_LEVEL,
    ),
    NeumannKHNumberDescription(
        key="output_dimm",
        translation_key="output_dimm",
        icon="mdi:volume-medium",
        native_min_value=DIMM_MIN,
        native_max_value=DIMM_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # nicht bei allen Modellen vorhanden
        ssc_path=PATH_OUTPUT_DIMM,
    ),
    NeumannKHNumberDescription(
        key="standby_auto_time",
        translation_key="standby_auto_time",
        icon="mdi:timer-sand",
        native_min_value=STANDBY_AUTO_TIME_MIN,
        native_max_value=STANDBY_AUTO_TIME_MAX,
        native_step=1,
        native_unit_of_measurement="min",
        mode=NumberMode.BOX,
        ssc_path=PATH_STANDBY_AUTO_TIME,
    ),
    NeumannKHNumberDescription(
        key="standby_level",
        translation_key="standby_level",
        icon="mdi:volume-off-outline",
        native_min_value=STANDBY_LEVEL_MIN,
        native_max_value=STANDBY_LEVEL_MAX,
        native_step=1,
        native_unit_of_measurement=STANDBY_LEVEL_UNIT,
        mode=NumberMode.BOX,
        ssc_path=PATH_STANDBY_LEVEL,
    ),
)

# Nur für Nicht-Subwoofer-Modelle verfügbar, siehe MODELS_WITH_LOGO_AND_SAVE
BRIGHTNESS_DESCRIPTION = NeumannKHNumberDescription(
    key="logo_brightness",
    translation_key="logo_brightness",
    icon="mdi:brightness-6",
    native_min_value=BRIGHTNESS_MIN,
    native_max_value=BRIGHTNESS_MAX,
    native_step=1,
    native_unit_of_measurement="%",
    mode=NumberMode.SLIDER,
    ssc_path=PATH_LOGO_BRIGHTNESS,
)

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES)
SUBWOOFER_NUMBER_DESCRIPTIONS: tuple[NeumannKHNumberDescription, ...] = (
    NeumannKHNumberDescription(
        key="out1_level",
        translation_key="out1_level",
        icon="mdi:volume-high",
        native_min_value=LEVEL_MIN,
        native_max_value=LEVEL_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # nur relevant, falls Out1 belegt ist
        ssc_path=PATH_OUT1_LEVEL,
    ),
    NeumannKHNumberDescription(
        key="out1_delay",
        translation_key="out1_delay",
        icon="mdi:timer-outline",
        native_min_value=DELAY_MIN,
        native_max_value=DELAY_MAX_SUBWOOFER,
        native_step=1,
        native_unit_of_measurement="samples",
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT1_DELAY,
        integer=True,
    ),
    NeumannKHNumberDescription(
        key="out2_level",
        translation_key="out2_level",
        icon="mdi:volume-high",
        native_min_value=LEVEL_MIN,
        native_max_value=LEVEL_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # nur relevant, falls Out2 belegt ist
        ssc_path=PATH_OUT2_LEVEL,
    ),
    NeumannKHNumberDescription(
        key="out2_delay",
        translation_key="out2_delay",
        icon="mdi:timer-outline",
        native_min_value=DELAY_MIN,
        native_max_value=DELAY_MAX_SUBWOOFER,
        native_step=1,
        native_unit_of_measurement="samples",
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
        ssc_path=PATH_OUT2_DELAY,
        integer=True,
    ),
)


def _build_output_delay_description(is_subwoofer: bool) -> NeumannKHNumberDescription:
    """Baut die Delay-Beschreibung des Hauptausgangs mit modellabhängigem Max-Wert."""
    return NeumannKHNumberDescription(
        key="output_delay",
        translation_key="output_delay",
        icon="mdi:timer-outline",
        native_min_value=DELAY_MIN,
        native_max_value=DELAY_MAX_SUBWOOFER if is_subwoofer else DELAY_MAX_DEFAULT,
        native_step=1,
        native_unit_of_measurement="samples",  # 1/48000s pro Sample
        mode=NumberMode.BOX,
        ssc_path=PATH_OUTPUT_DELAY,
        integer=True,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Number-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    model = entry.data.get(CONF_MODEL)
    is_subwoofer = model in MODELS_WITH_SUBWOOFER_FEATURES

    descriptions = list(COMMON_NUMBER_DESCRIPTIONS)
    descriptions.append(_build_output_delay_description(is_subwoofer))

    if model in MODELS_WITH_LOGO_AND_SAVE:
        descriptions.append(BRIGHTNESS_DESCRIPTION)

    if is_subwoofer:
        descriptions.extend(SUBWOOFER_NUMBER_DESCRIPTIONS)

    async_add_entities(
        NeumannKHNumber(coordinator, entry, description) for description in descriptions
    )


class NeumannKHNumber(NeumannKHEntity, NumberEntity):
    """Schreibbarer Zahlenwert eines Neumann-KH-Lautsprechers."""

    entity_description: NeumannKHNumberDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        # Defensive Konvertierung: nicht-numerischer Wert -> "unbekannt" statt Exception.
        try:
            return float(value)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Nicht-numerischer Wert für %s: %r - zeige 'unbekannt'",
                self.entity_description.key,
                value,
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Schreibt den neuen Wert per SSC "set" und aktualisiert danach den Cache."""
        payload_value: Any = int(value) if self.entity_description.integer else float(value)

        try:
            confirmed = await self.coordinator.client.set(
                self.entity_description.ssc_path, payload_value
            )
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        except (SSCConnectionError, SSCTimeoutError) as err:
            raise HomeAssistantError(f"Der Lautsprecher ist nicht erreichbar: {err}") from err
        await self._apply_confirmed_value(self.entity_description.ssc_path, confirmed)
