"""Number-Entities: Level, Dimm, Delay, Logo-Helligkeit, Auto-Standby-Werte,
Eingangsverstärkung (Nicht-Subwoofer) sowie (nur bei erkanntem Subwoofer)
Subwoofer-Kalibrierung und die beiden zusätzlichen Bass-Management-Ausgänge
out1/out2.

Jede Number-Entity liest ihren aktuellen Wert aus dem Coordinator-Cache und
schreibt bei Änderung direkt per SSC "set" auf den Lautsprecher. Danach wird
ein sofortiger Refresh angestoßen, damit der neue Wert zeitnah in HA sichtbar
ist, statt bis zum nächsten Poll-Zyklus zu warten.

WICHTIG zu den Wertebereichen: Diese sind gegen khtools interne
"khtool_commands.json"-Metadaten verifiziert (siehe const.py-Moduldocstring
zur Zuverlässigkeit dieser Quelle) - deutlich genauer als die ursprünglichen
Schätzwerte. Die KLANGREGLER (Bass/Mitten/Höhen) und die SUBWOOFER-PHASE
wurden dabei als feste String-Enums (nicht als kontinuierlicher
Zahlenbereich) identifiziert und deshalb nach select.py verschoben.

Hinweis zu "Dimm": Per echtem Hardware-Test (khtool) auf einer KH 120 II
(Firmware 1_7_3) bestätigt NICHT vorhanden - das Gerät lehnt sowohl das
Lesen als auch das Setzen mit einem OSC-Fehler ab. Die Entity bleibt trotzdem
bestehen (evtl. bei anderen Modellen vorhanden) und zeigt in diesem Fall
"unknown" bzw. wirft beim Setzen einen klaren Fehler.
"""

from __future__ import annotations

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
    INPUT_GAIN_MAX,
    INPUT_GAIN_MIN,
    LEVEL_MAX,
    LEVEL_MIN,
    MODELS_WITH_LOGO_AND_SAVE,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_INPUT_GAIN,
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
    PATH_UI_SUB_INPUT_GAIN,
    PATH_UI_SUB_LOW_CUT,
    STANDBY_AUTO_TIME_MAX,
    STANDBY_AUTO_TIME_MIN,
    STANDBY_LEVEL_MAX,
    STANDBY_LEVEL_MIN,
    STANDBY_LEVEL_UNIT,
    SUB_INPUT_GAIN_MAX,
    SUB_INPUT_GAIN_MIN,
    SUB_LOW_CUT_MAX,
    SUB_LOW_CUT_MIN,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


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
        entity_registry_enabled_default=False,  # auf KH 120 II nicht vorhanden, siehe README
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

# Nur für KH 80 / KH 150 / KH 120 II verfügbar (nicht KH 750)
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

# Nur bei Nicht-Subwoofer-Modellen (existiert laut khtool-Metadaten nur dort)
INPUT_GAIN_DESCRIPTION = NeumannKHNumberDescription(
    key="input_gain",
    translation_key="input_gain",
    icon="mdi:tune-vertical",
    native_min_value=INPUT_GAIN_MIN,
    native_max_value=INPUT_GAIN_MAX,
    native_step=0.5,
    native_unit_of_measurement="dB",
    mode=NumberMode.SLIDER,
    ssc_path=PATH_INPUT_GAIN,
)

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES)
SUBWOOFER_NUMBER_DESCRIPTIONS: tuple[NeumannKHNumberDescription, ...] = (
    NeumannKHNumberDescription(
        key="subwoofer_input_gain",
        translation_key="subwoofer_input_gain",
        icon="mdi:tune-vertical",
        native_min_value=SUB_INPUT_GAIN_MIN,
        native_max_value=SUB_INPUT_GAIN_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        ssc_path=PATH_UI_SUB_INPUT_GAIN,
    ),
    NeumannKHNumberDescription(
        key="subwoofer_low_cut",
        translation_key="subwoofer_low_cut",
        icon="mdi:sine-wave",
        native_min_value=SUB_LOW_CUT_MIN,
        native_max_value=SUB_LOW_CUT_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.BOX,
        ssc_path=PATH_UI_SUB_LOW_CUT,
    ),
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
    """Baut die Delay-Beschreibung des Hauptausgangs mit modellabhängigem Max-Wert.

    KH 120 II (und andere Nicht-Subwoofer-Modelle): 0-5760 Samples.
    KH 750: 0-1000 Samples (Hauptausgang, ebenso wie out1/out2).
    """
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
    else:
        descriptions.append(INPUT_GAIN_DESCRIPTION)

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
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Schreibt den neuen Wert per SSC "set" und aktualisiert danach den Cache."""
        payload_value: Any = int(value) if self.entity_description.integer else float(value)

        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, payload_value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self.coordinator.async_request_refresh()
