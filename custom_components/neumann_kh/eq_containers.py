"""EQ-Container-Definitionen (Pfad-Präfix, Bänderzahl, Anzeigename).

Eigenes Modul ohne Entity-/Coordinator-Importe, damit sowohl coordinator.py
(Polling) als auch eq.py (Entities) darauf zugreifen können, ohne einen
Zirkelimport zu erzeugen.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import MODELS_WITH_SUBWOOFER_FEATURES


@dataclass(frozen=True, kw_only=True)
class EQContainer:
    """Ein EQ-Container (Pfad-Präfix, Bänderzahl, Anzeigename)."""

    path: tuple[str, ...]
    band_count: int
    label: str


# Nicht-Subwoofer-Modelle (KH 120 II etc.)
NON_SUBWOOFER_EQ_CONTAINERS: tuple[EQContainer, ...] = (
    EQContainer(path=("audio", "out", "eq2"), band_count=10, label="EQ2 Hauptausgang"),
    EQContainer(path=("audio", "out", "eq3"), band_count=20, label="EQ3 Hauptausgang"),
)

# Subwoofer (KH 750): Hauptausgang + out1/out2, je mit Crossover (eq1, nur
# out1/out2) sowie eq2/eq3. Alle Labels beginnen bewusst mit "EQ", damit sie
# in der Konfiguration-Sektion alphabetisch zusammen gruppiert erscheinen.
SUBWOOFER_EQ_CONTAINERS: tuple[EQContainer, ...] = (
    EQContainer(path=("audio", "out", "eq2"), band_count=10, label="EQ2 Subwoofer-Hauptausgang"),
    EQContainer(path=("audio", "out1", "eq1"), band_count=2, label="EQ Crossover Ausgang 1"),
    EQContainer(path=("audio", "out1", "eq2"), band_count=10, label="EQ2 Ausgang 1"),
    EQContainer(path=("audio", "out1", "eq3"), band_count=10, label="EQ3 Ausgang 1"),
    EQContainer(path=("audio", "out2", "eq1"), band_count=2, label="EQ Crossover Ausgang 2"),
    EQContainer(path=("audio", "out2", "eq2"), band_count=10, label="EQ2 Ausgang 2"),
    EQContainer(path=("audio", "out2", "eq3"), band_count=10, label="EQ3 Ausgang 2"),
)


def eq_containers_for_model(model: str | None) -> tuple[EQContainer, ...]:
    """Liefert die passenden EQ-Container für das jeweilige Modell."""
    if model in MODELS_WITH_SUBWOOFER_FEATURES:
        return SUBWOOFER_EQ_CONTAINERS
    return NON_SUBWOOFER_EQ_CONTAINERS
