"""EQ container definitions (path prefix, band count, display name).

Separate module without entity/coordinator imports, so that both
coordinator.py (polling) and eq.py (entities) can access it without creating
a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import MODELS_WITH_SUBWOOFER_FEATURES


@dataclass(frozen=True, kw_only=True)
class EQContainer:
    """An EQ container (path prefix, band count, display name).

    The display name has no translation_key mechanism (it is interpolated into
    entity names via translation_placeholders), so both language variants are
    stored here and chosen at runtime from the HA language.
    """

    path: tuple[str, ...]
    band_count: int
    label_en: str
    label_de: str

    def label_for(self, language: str | None) -> str:
        """Return the display label for the given HA language (de/en, fallback en)."""
        if language and language.startswith("de"):
            return self.label_de
        return self.label_en


# Non-subwoofer models (KH 120 II etc.)
NON_SUBWOOFER_EQ_CONTAINERS: tuple[EQContainer, ...] = (
    EQContainer(
        path=("audio", "out", "eq2"), band_count=10,
        label_en="EQ2 Main output", label_de="EQ2 Hauptausgang",
    ),
    EQContainer(
        path=("audio", "out", "eq3"), band_count=20,
        label_en="EQ3 Main output", label_de="EQ3 Hauptausgang",
    ),
)

# Subwoofer (KH 750): main output + out1/out2, each with crossover (eq1, only
# out1/out2) plus eq2/eq3. All labels deliberately begin with "EQ" so they
# appear grouped together alphabetically in the configuration section.
SUBWOOFER_EQ_CONTAINERS: tuple[EQContainer, ...] = (
    EQContainer(
        path=("audio", "out", "eq2"), band_count=10,
        label_en="EQ2 Subwoofer main output", label_de="EQ2 Subwoofer-Hauptausgang",
    ),
    EQContainer(
        path=("audio", "out1", "eq1"), band_count=2,
        label_en="EQ Crossover Output 1", label_de="EQ Crossover Ausgang 1",
    ),
    EQContainer(
        path=("audio", "out1", "eq2"), band_count=10,
        label_en="EQ2 Output 1", label_de="EQ2 Ausgang 1",
    ),
    EQContainer(
        path=("audio", "out1", "eq3"), band_count=10,
        label_en="EQ3 Output 1", label_de="EQ3 Ausgang 1",
    ),
    EQContainer(
        path=("audio", "out2", "eq1"), band_count=2,
        label_en="EQ Crossover Output 2", label_de="EQ Crossover Ausgang 2",
    ),
    EQContainer(
        path=("audio", "out2", "eq2"), band_count=10,
        label_en="EQ2 Output 2", label_de="EQ2 Ausgang 2",
    ),
    EQContainer(
        path=("audio", "out2", "eq3"), band_count=10,
        label_en="EQ3 Output 2", label_de="EQ3 Ausgang 2",
    ),
)


def eq_containers_for_model(model: str | None) -> tuple[EQContainer, ...]:
    """Returns the matching EQ containers for the given model."""
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        return SUBWOOFER_EQ_CONTAINERS
    return NON_SUBWOOFER_EQ_CONTAINERS
