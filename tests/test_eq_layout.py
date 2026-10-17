"""The KH 750 EQ layout, as measured on the device.

Read-only probe of two KH 750 (firmware 2_1_2): eq2 and eq3 exist on the main
output and on out1/out2, ten bands each; eq1 exists nowhere (404). The table
used to carry an eq1 "crossover" on out1/out2 - two switches stuck at unknown,
two reset buttons failing on every press - and lacked eq3 on the main output.

The integration's table and the simulator are both checked against this one
measured list, so neither can drift away from the device by mirroring the
other.
"""

from __future__ import annotations

from custom_components.neumann_kh.eq_containers import SUBWOOFER_EQ_CONTAINERS
from tools.ssc_simulator import MODEL_KH_750, SSCSimulator

MEASURED_KH_750 = {
    (("audio", "out", "eq2"), 10),
    (("audio", "out", "eq3"), 10),
    (("audio", "out1", "eq2"), 10),
    (("audio", "out1", "eq3"), 10),
    (("audio", "out2", "eq2"), 10),
    (("audio", "out2", "eq3"), 10),
}


def test_the_integration_knows_exactly_the_measured_kh750_containers():
    table = {(container.path, container.band_count) for container in SUBWOOFER_EQ_CONTAINERS}
    assert table == MEASURED_KH_750


def test_the_simulator_answers_like_the_measured_kh750():
    simulator = SSCSimulator(MODEL_KH_750)
    for path, bands in MEASURED_KH_750:
        answer = simulator.handle(_nested(path + ("enabled",)))
        assert "osc" not in answer, path
        enabled = answer["audio"][path[1]][path[2]]["enabled"]
        assert len(enabled) == bands, path
    for output in ("out", "out1", "out2"):
        answer = simulator.handle(_nested(("audio", output, "eq1", "enabled")))
        assert answer["osc"]["error"][0] == 404, output


def _nested(path: tuple[str, ...]) -> dict:
    tree: object = None
    for key in reversed(path):
        tree = {key: tree}
    return tree
