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
    KH_120_II_READ_ONLY_SET_REPLIES,
    KH_750_NOT_FOUND_REPLIES,
    KH_750_SWITCH_SET_REPLIES,
    LOCAL_MODE_SET_REPLY,
    LIMITS_LEVEL_REQUEST,
    LIMITS_LEVEL_TYPE,
    MALFORMED_OSC_REPLIES,
    NOT_FOUND_REPLIES,
    OSC_METHOD_REPLIES,
    SCHEMA_AUDIO_REPLIES,
    SCHEMA_AUDIO_REQUEST,
    SCHEMA_ROOT_REPLY,
    SET_REPLIES,
    SWITCH_SET_REPLIES,
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


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    ("request_", "line"),
    SET_REPLIES,
    ids=["set", "set-missing", "set-wrong-type", "bundle-set", "bundle-set-missing", "get-and-set"],
)
def test_the_simulator_answers_sets_like_the_device(model, request_, line):
    """Recorded with values equal to the simulator's defaults (mute off, delay 0)."""
    assert SSCSimulator(model).handle(request_) == json.loads(line)


@pytest.mark.parametrize(
    ("request_", "line"), KH_120_II_READ_ONLY_SET_REPLIES, ids=["read-only", "bundle-read-only"]
)
def test_the_simulated_kh_120_ii_refuses_read_only_sets_like_the_device(request_, line):
    assert SSCSimulator(MODEL_KH_120_II).handle(request_) == json.loads(line)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(("request_", "line"), SWITCH_SET_REPLIES, ids=["control-mode"])
def test_the_simulator_refuses_switch_settings_like_the_device(model, request_, line):
    assert SSCSimulator(model).handle(request_) == json.loads(line)


@pytest.mark.parametrize(("request_", "line"), KH_750_SWITCH_SET_REPLIES, ids=["auto-standby"])
def test_the_simulated_kh_750_refuses_its_auto_standby_switch(request_, line):
    assert SSCSimulator(MODEL_KH_750).handle(request_) == json.loads(line)


@pytest.mark.parametrize("model", MODELS)
def test_a_simulator_in_local_mode_answers_like_the_device(model):
    """Measured on a KH 750; the KH 120 II has the same CONTROL switch."""
    simulator = SSCSimulator(model, local_mode=True)
    request_, line = LOCAL_MODE_SET_REPLY

    assert simulator.handle(request_) == json.loads(line)
    assert _get(simulator, "audio", "out", "mute") is False
    assert _get(simulator, "ui", "control_mode") == "LOCAL"


@pytest.mark.parametrize("model", MODELS)
def test_the_simulator_describes_its_tree_like_the_device(model):
    simulator = SSCSimulator(model)
    assert simulator.handle(SCHEMA_ROOT_REPLY[0]) == json.loads(SCHEMA_ROOT_REPLY[1])
    assert simulator.handle(SCHEMA_AUDIO_REQUEST) == json.loads(SCHEMA_AUDIO_REPLIES[model])


@pytest.mark.parametrize("model", MODELS)
def test_the_simulator_reports_limits_like_the_device(model):
    reply = SSCSimulator(model).handle(LIMITS_LEVEL_REQUEST)
    limits = reply["osc"]["limits"][0]["audio"]["out"]["level"]
    assert isinstance(limits, list)
    assert len(limits) == 1
    assert limits[0]["type"] == LIMITS_LEVEL_TYPE


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    ("request_", "line"),
    MALFORMED_OSC_REPLIES,
    ids=["schema-null", "schema-empty", "limits-no-list"],
)
def test_the_simulator_refuses_malformed_introspection_like_the_device(model, request_, line):
    assert SSCSimulator(model).handle(request_) == json.loads(line)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    ("request_", "line"),
    OSC_METHOD_REPLIES,
    ids=["version", "pattern", "subscription", "ping", "xid-number", "xid-text"],
)
def test_the_simulator_answers_osc_methods_like_the_device(model, request_, line):
    assert SSCSimulator(model).handle(request_) == json.loads(line)


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
