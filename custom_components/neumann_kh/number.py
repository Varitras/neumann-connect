"""Number-Entities: Level, Dimm, Delay, Logo-Helligkeit, Auto-Standby-Werte, Klangregler.

Jede Number-Entity liest ihren aktuellen Wert aus dem Coordinator-Cache und
schreibt bei Änderung direkt per SSC "set" auf den Lautsprecher. Danach wird
ein sofortiger Refresh angestoßen, damit der neue Wert zeitnah in HA sichtbar
ist, statt bis zum nächsten Poll-Zyklus zu warten.

Hinweis zu "Dimm": Per echtem Hardware-Test (khtool) auf einer KH 120 II
(Firmware 1_7_3) bestätigt NICHT vorhanden - das Gerät lehnt sowohl das
Lesen als auch das Setzen mit einem OSC-Fehler ab. Die Entity bleibt trotzdem
bestehen (evtl. bei anderen Modellen wie der KH 750 DSP vorhanden) und zeigt
in diesem Fall "unknown" bzw. wirft beim Setzen einen klaren Fehler (siehe
async_set_native_value).

Hinweis zu den Klangreglern (Bass/Mitten/Höhen) UND den Auto-Standby-Werten:
Wertebereiche sind NICHT offiziell dokumentiert und NICHT gegen echte
Hardware verifiziert - konservativ geschätzt. Lehnt das Gerät einen Wert ab,
zeigt HA eine klare Fehlermeldung statt eines stillen Fehlschlags oder gar
eines unerwarteten Verhaltens am Gerät.
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
    DELAY_MAX,
    DELAY_MIN,
    DIMM_MAX,
    DIMM_MIN,
    DOMAIN,
    LEVEL_MAX,
    LEVEL_MIN,
    MODELS_WITH_LOGO_AND_SAVE,
    PATH_LOGO_BRIGHTNESS,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_LEVEL,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_TREBLE_GAIN,
    STANDBY_AUTO_TIME_MAX,
    STANDBY_AUTO_TIME_MIN,
    STANDBY_LEVEL_MAX,
    STANDBY_LEVEL_MIN,
    TONE_GAIN_MAX,
    TONE_GAIN_MIN,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHNumberDescription(NumberEntityDescription):
    """Beschreibung einer Number-Entity inkl. SSC-Pfad.

    value_is_string: Manche SSC-Eigenschaften (z. B. die Klangregler)
    liefern ihren Wert als JSON-STRING (z. B. "0") statt als Zahl. Beim
    Lesen ist das unproblematisch (float("0") funktioniert), beim
    SCHREIBEN muss der Wert aber als String zurückgeschickt werden, sonst
    könnte das Gerät die Anfrage ablehnen.
    """

    ssc_path: tuple[str, ...] = ()
    value_is_string: bool = False


NUMBER_DESCRIPTIONS: tuple[NeumannKHNumberDescription, ...] = (
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
        key="output_delay",
        translation_key="output_delay",
        icon="mdi:timer-outline",
        native_min_value=DELAY_MIN,
        native_max_value=DELAY_MAX,
        native_step=1,
        native_unit_of_measurement="samples",  # 1/48000s pro Sample, siehe khtool --delay
        mode=NumberMode.BOX,
        ssc_path=PATH_OUTPUT_DELAY,
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
        entity_registry_enabled_default=False,  # Wertebereich unverifiziert, siehe README
        ssc_path=PATH_STANDBY_AUTO_TIME,
    ),
    NeumannKHNumberDescription(
        key="standby_level",
        translation_key="standby_level",
        icon="mdi:volume-off-outline",
        native_min_value=STANDBY_LEVEL_MIN,
        native_max_value=STANDBY_LEVEL_MAX,
        native_step=1,
        native_unit_of_measurement="dB",
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,  # Wertebereich unverifiziert, siehe README
        ssc_path=PATH_STANDBY_LEVEL,
    ),
    NeumannKHNumberDescription(
        key="bass_gain",
        translation_key="bass_gain",
        icon="mdi:sine-wave",
        native_min_value=TONE_GAIN_MIN,
        native_max_value=TONE_GAIN_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # Wertebereich unverifiziert, siehe README
        ssc_path=PATH_UI_BASS_GAIN,
        value_is_string=True,
    ),
    NeumannKHNumberDescription(
        key="mid_gain",
        translation_key="mid_gain",
        icon="mdi:sine-wave",
        native_min_value=TONE_GAIN_MIN,
        native_max_value=TONE_GAIN_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # Wertebereich unverifiziert, siehe README
        ssc_path=PATH_UI_MID_GAIN,
        value_is_string=True,
    ),
    NeumannKHNumberDescription(
        key="treble_gain",
        translation_key="treble_gain",
        icon="mdi:sine-wave",
        native_min_value=TONE_GAIN_MIN,
        native_max_value=TONE_GAIN_MAX,
        native_step=0.5,
        native_unit_of_measurement="dB",
        mode=NumberMode.SLIDER,
        entity_registry_enabled_default=False,  # Wertebereich unverifiziert, siehe README
        ssc_path=PATH_UI_TREBLE_GAIN,
        value_is_string=True,
    ),
)

# Nur für KH 80 / KH 150 / KH 120 II verfügbar (nicht KH 750 DSP)
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Number-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = list(NUMBER_DESCRIPTIONS)
    if entry.data.get(CONF_MODEL) in MODELS_WITH_LOGO_AND_SAVE:
        descriptions.append(BRIGHTNESS_DESCRIPTION)

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
        # Delay ist ein Integer (Samples), Klangregler werden als STRING
        # zurückgeschickt (siehe value_is_string-Doku oben), alle anderen
        # Werte sind normale Fließkomma-dB-Werte.
        payload_value: Any
        if self.entity_description.value_is_string:
            payload_value = str(value)
        elif self.entity_description.ssc_path == PATH_OUTPUT_DELAY:
            payload_value = int(value)
        else:
            payload_value = float(value)

        try:
            await self.coordinator.client.set(self.entity_description.ssc_path, payload_value)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Änderung abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self.coordinator.async_request_refresh()
