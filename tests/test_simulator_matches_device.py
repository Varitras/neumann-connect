"""The simulator answers the way the real speakers were recorded answering.

Every end-to-end test talks to the simulator, so wherever it invents its own
format the suite proves the integration against something no speaker sends.
That is how a parser that read no error code from real hardware stayed green.
The replies are from a read-only probe of 2026-10-17 (KH 120 II 1_7_3, KH 750
2_1_2); see recorded_replies.py.
"""

from __future__ import annotations

import json

import pytest
from recorded_replies import (
    BUNDLE_REPLY,
    CONTAINER_REPLY,
    KH_750_NOT_FOUND_REPLIES,
    NOT_FOUND_REPLIES,
)

from tools.ssc_simulator import MODEL_KH_120_II, MODEL_KH_750, SSCSimulator

MODELS = (MODEL_KH_120_II, MODEL_KH_750)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    ("request_", "line"),
    NOT_FOUND_REPLIES + (CONTAINER_REPLY, BUNDLE_REPLY),
    ids=["leaf", "missing-container", "save-settings", "container-query", "bundle"],
)
def test_the_simulator_answers_like_the_device(model, request_, line):
    assert SSCSimulator(model).handle(request_) == json.loads(line)


@pytest.mark.parametrize(("request_", "line"), KH_750_NOT_FOUND_REPLIES)
def test_the_simulated_kh_750_answers_like_the_device(request_, line):
    assert SSCSimulator(MODEL_KH_750).handle(request_) == json.loads(line)


def _get(simulator: SSCSimulator, *path: str):
    request: object = None
    for key in reversed(path):
        request = {key: request}
    answer = simulator.handle(request)
    for key in path:
        answer = answer[key]
    return answer


@pytest.mark.parametrize("model", MODELS)
def test_the_hardware_version_is_a_number(model):
    assert type(_get(SSCSimulator(model), "device", "identity", "hw_version")) is int


def test_the_kh_750_meters_three_outputs():
    """Measured: output level and clip carry [A, B, subwoofer]."""
    simulator = SSCSimulator(MODEL_KH_750)
    assert len(_get(simulator, "m", "out", "level")) == 3
    assert len(_get(simulator, "m", "out", "clip")) == 3


@pytest.mark.parametrize(
    ("output", "filter_type"), [("out", "LOWPASS"), ("out1", "HIGHPASS"), ("out2", "HIGHPASS")]
)
@pytest.mark.parametrize("sub", ["in1", "in2"])
def test_the_kh_750_crossover_sits_under_eq1_inputs(output, filter_type, sub):
    simulator = SSCSimulator(MODEL_KH_750)
    assert _get(simulator, "audio", output, "eq1", sub, "type") == [filter_type, filter_type]
    assert _get(simulator, "audio", output, "eq1", sub, "frequency") == [80.0, 80.0]


def test_the_kh_750_has_the_auto_standby_mode():
    assert _get(SSCSimulator(MODEL_KH_750), "ui", "auto_standby") in ("OFF", "ON")
