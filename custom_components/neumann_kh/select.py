"""Select-Entities: feste Wertauswahlen (String-Enums), keine kontinuierlichen
Zahlenbereiche.

Alle Wertebereiche/Optionen unten stammen aus khtools interner
"khtool_commands.json"-Metadaten-Datenbank (siehe const.py-Moduldocstring
zur Zuverlässigkeit dieser Quelle).

Standard-Aktivierung: Für Nicht-Subwoofer-Modelle (KH 120 II etc.) sind alle
Entities standardmäßig AKTIVIERT (bis auf die unten explizit genannte
Ausnahme) - "Dimm" existiert dort ohnehin nicht (siehe number.py) und
scheidet daher automatisch aus.

BEWUSSTE SICHERHEITS-AUSNAHME (gilt für ALLE Modelle): "Steuerungsmodus"
(NETWORK/LOCAL) bleibt IMMER standardmäßig deaktiviert. Ein Wechsel zu LOCAL
könnte die Netzwerksteuerung - und damit diese Integration - komplett vom
Gerät trennen, bis manuell am Gerät zurückgestellt wird. Das ist eine
bewusste Abweichung von "alles außer Dimm aktivieren", da hier ein
Aussperr-Risiko besteht, kein bloßes "der Wert könnte falsch sein".

Für den Subwoofer bleiben Bass-Management/Kanal-B-Eingangsmodus ebenfalls
standardmäßig deaktiviert: ein falscher Wert könnte die Ausgangsroutung des
gesamten Systems durcheinanderbringen.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BASS_GAIN_OPTIONS,
    BASS_MANAGEMENT_OPTIONS,
    CHANNEL_B_INPUT_MODE_OPTIONS,
    CONF_MODEL,
    CONTROL_MODE_OPTIONS,
    DOMAIN,
    INPUT_INTERFACE_OPTIONS,
    INPUT_SELECT_OPTIONS,
    MID_GAIN_OPTIONS,
    MODELS_WITH_SUBWOOFER_FEATURES,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_INPUT_SELECT,
    PATH_UI_BASS_GAIN,
    PATH_UI_BASS_MANAGEMENT,
    PATH_UI_CHANNEL_B_INPUT_MODE,
    PATH_UI_CONTROL_MODE,
    PATH_UI_MID_GAIN,
    PATH_UI_OUTPUT_LEVEL,
    PATH_UI_SUB_OUTPUT_LEVEL,
    PATH_UI_SUB_PHASE,
    PATH_UI_SUB_PHASE_INVERSION,
    PATH_UI_TREBLE_GAIN,
    SUB_OUTPUT_LEVEL_OPTIONS,
    SUB_PHASE_INVERSION_OPTIONS,
    SUB_PHASE_OPTIONS,
    TREBLE_GAIN_OPTIONS,
)
from .coordinator import NeumannKHCoordinator
from .entity import NeumannKHEntity
from .ssc_client import SSCDeviceError


@dataclass(frozen=True, kw_only=True)
class NeumannKHSelectDescription(SelectEntityDescription):
    """Beschreibung einer Select-Entity inkl. SSC-Pfad."""

    ssc_path: tuple[str, ...] = ()


# IMMER angelegt (modellunabhängig) - bewusste Sicherheits-Ausnahme, siehe
# Moduldocstring: bleibt IMMER deaktiviert, unabhängig vom Modell.
CONTROL_MODE_DESCRIPTION = NeumannKHSelectDescription(
    key="control_mode",
    translation_key="control_mode",
    icon="mdi:network-outline",
    options=list(CONTROL_MODE_OPTIONS),
    entity_registry_enabled_default=False,  # Wechsel zu LOCAL kappt die Netzwerksteuerung!
    ssc_path=PATH_UI_CONTROL_MODE,
)


def _build_input_interface_description(is_subwoofer: bool) -> NeumannKHSelectDescription:
    """Baut die 'Eingangs-Interface'-Beschreibung mit modellabhängigem Standard.

    Bei Nicht-Subwoofer-Modellen (z. B. KH 120 II) standardmäßig aktiviert
    (Teil von "alle KH-120-Entities außer Dimm aktivieren"). Beim Subwoofer
    bleibt sie vorsichtshalber deaktiviert, da dieser Pfad dort noch nicht
    im selben Umfang durchgetestet wurde.
    """
    return NeumannKHSelectDescription(
        key="input_interface",
        translation_key="input_interface",
        icon="mdi:audio-input-stereo-minijack",
        options=list(INPUT_INTERFACE_OPTIONS),
        entity_registry_enabled_default=not is_subwoofer,
        ssc_path=PATH_INPUT_INTERFACE_TYPE,
    )


# Nur bei Nicht-Subwoofer-Modellen (existieren laut khtool-Metadaten nur dort)
# - standardmäßig aktiviert, siehe "alle KH-120-Entities außer Dimm".
NON_SUBWOOFER_SELECT_DESCRIPTIONS: tuple[NeumannKHSelectDescription, ...] = (
    NeumannKHSelectDescription(
        key="bass_gain",
        translation_key="bass_gain",
        icon="mdi:sine-wave",
        options=list(BASS_GAIN_OPTIONS),
        ssc_path=PATH_UI_BASS_GAIN,
    ),
    NeumannKHSelectDescription(
        key="mid_gain",
        translation_key="mid_gain",
        icon="mdi:sine-wave",
        options=list(MID_GAIN_OPTIONS),
        ssc_path=PATH_UI_MID_GAIN,
    ),
    NeumannKHSelectDescription(
        key="treble_gain",
        translation_key="treble_gain",
        icon="mdi:sine-wave",
        options=list(TREBLE_GAIN_OPTIONS),
        ssc_path=PATH_UI_TREBLE_GAIN,
    ),
    NeumannKHSelectDescription(
        key="output_level",
        translation_key="output_level_select",
        icon="mdi:volume-high",
        options=list(SUB_OUTPUT_LEVEL_OPTIONS),  # identische Stufen wie beim Subwoofer-Pendant
        ssc_path=PATH_UI_OUTPUT_LEVEL,
    ),
    NeumannKHSelectDescription(
        key="input_select",
        translation_key="input_select",
        icon="mdi:audio-input-rca",
        options=list(INPUT_SELECT_OPTIONS),
        ssc_path=PATH_INPUT_SELECT,
    ),
)

# Nur bei erkanntem Subwoofer (siehe MODELS_WITH_SUBWOOFER_FEATURES) - bleibt
# vorsichtshalber deaktiviert (falscher Wert kann Ausgangsroutung durcheinanderbringen).
SUBWOOFER_SELECT_DESCRIPTIONS: tuple[NeumannKHSelectDescription, ...] = (
    NeumannKHSelectDescription(
        key="subwoofer_output_level",
        translation_key="subwoofer_output_level",
        icon="mdi:volume-high",
        options=list(SUB_OUTPUT_LEVEL_OPTIONS),
        ssc_path=PATH_UI_SUB_OUTPUT_LEVEL,
    ),
    NeumannKHSelectDescription(
        key="subwoofer_phase",
        translation_key="subwoofer_phase",
        icon="mdi:rotate-360",
        options=list(SUB_PHASE_OPTIONS),
        ssc_path=PATH_UI_SUB_PHASE,
    ),
    NeumannKHSelectDescription(
        key="subwoofer_phase_inversion",
        translation_key="subwoofer_phase_inversion",
        icon="mdi:sine-wave",
        options=list(SUB_PHASE_INVERSION_OPTIONS),
        ssc_path=PATH_UI_SUB_PHASE_INVERSION,
    ),
    NeumannKHSelectDescription(
        key="bass_management",
        translation_key="bass_management",
        icon="mdi:speaker",
        options=list(BASS_MANAGEMENT_OPTIONS),
        entity_registry_enabled_default=False,
        ssc_path=PATH_UI_BASS_MANAGEMENT,
    ),
    NeumannKHSelectDescription(
        key="channel_b_input_mode",
        translation_key="channel_b_input_mode",
        icon="mdi:import",
        options=list(CHANNEL_B_INPUT_MODE_OPTIONS),
        entity_registry_enabled_default=False,
        ssc_path=PATH_UI_CHANNEL_B_INPUT_MODE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Select-Entities für einen Lautsprecher an."""
    coordinator: NeumannKHCoordinator = hass.data[DOMAIN][entry.entry_id]
    is_subwoofer = entry.data.get(CONF_MODEL) in MODELS_WITH_SUBWOOFER_FEATURES

    descriptions = [
        CONTROL_MODE_DESCRIPTION,
        _build_input_interface_description(is_subwoofer),
    ]
    if is_subwoofer:
        descriptions.extend(SUBWOOFER_SELECT_DESCRIPTIONS)
    else:
        descriptions.extend(NON_SUBWOOFER_SELECT_DESCRIPTIONS)

    async_add_entities(
        NeumannKHSelect(coordinator, entry, description) for description in descriptions
    )


class NeumannKHSelect(NeumannKHEntity, SelectEntity):
    """Feste Auswahl (String-Enum) eines Neumann-KH-Lautsprechers."""

    entity_description: NeumannKHSelectDescription

    def __init__(
        self,
        coordinator: NeumannKHCoordinator,
        entry: ConfigEntry,
        description: NeumannKHSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{self._unique_id_base}_{description.key}"

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.value(self.entity_description.ssc_path)
        if value is None:
            return None
        return str(value)

    async def async_select_option(self, option: str) -> None:
        try:
            confirmed = await self.coordinator.client.set(self.entity_description.ssc_path, option)
        except SSCDeviceError as err:
            raise HomeAssistantError(
                f"Der Lautsprecher hat diese Auswahl abgelehnt (evtl. von diesem "
                f"Modell/dieser Firmware nicht unterstützt): {err}"
            ) from err
        await self._apply_confirmed_value(self.entity_description.ssc_path, confirmed)
