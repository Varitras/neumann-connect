"""Which container a KH 750 keeps its output level and mute in.

Firmware 1.2.x moved them from audio/out to audio/out5 (reported for 1.2.4;
2_1_2 uses audio/out, measured). The integration asks once at setup and falls
back to audio/out for anything that is not a clear answer: out5 is used only
when audio/out/level is a 404 AND audio/out5/level answers with a real number.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import _async_select_output_paths
from custom_components.neumann_kh.const import (
    CONF_MODEL,
    OUT5_OUTPUT_ALIASES,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_LEVEL_OUT5,
)
from custom_components.neumann_kh.ssc_client import (
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
)

NOT_ASKED = object()


class _Client:
    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.asked: list[tuple[str, ...]] = []
        self.installed_aliases = None

    async def get(self, path):
        self.asked.append(path)
        answer = self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def use_path_aliases(self, aliases):
        self.installed_aliases = aliases


def _entry(model: str):
    return SimpleNamespace(title="Sub", data={CONF_MODEL: model})


def _not_found() -> SSCDeviceError:
    return SSCDeviceError("rejected", code=404)


@pytest.mark.parametrize(
    ("out_answer", "out5_answer", "expected_aliases", "asks_out5"),
    [
        pytest.param(100.0, NOT_ASKED, None, False, id="out-answers"),
        pytest.param(None, NOT_ASKED, None, False, id="out-none"),
        pytest.param(SSCTimeoutError("t"), NOT_ASKED, None, False, id="out-timeout"),
        pytest.param(SSCConnectionError("c"), NOT_ASKED, None, False, id="out-connection-error"),
        pytest.param(SSCDeviceError("x", code=400), NOT_ASKED, None, False, id="out-400"),
        pytest.param(SSCDeviceError("x"), NOT_ASKED, None, False, id="out-404-code-missing"),
        pytest.param(_not_found(), 87.0, OUT5_OUTPUT_ALIASES, True, id="out5-number"),
        pytest.param(_not_found(), 87, OUT5_OUTPUT_ALIASES, True, id="out5-int"),
        pytest.param(_not_found(), _not_found(), None, True, id="out5-404"),
        pytest.param(_not_found(), None, None, True, id="out5-none"),
        pytest.param(_not_found(), SSCTimeoutError("t"), None, True, id="out5-timeout"),
        pytest.param(_not_found(), True, None, True, id="out5-bool"),
        pytest.param(_not_found(), "100", None, True, id="out5-text"),
        pytest.param(_not_found(), math.nan, None, True, id="out5-nan"),
    ],
)
async def test_the_output_container_falls_back_to_out_unless_out5_is_conclusive(
    out_answer, out5_answer, expected_aliases, asks_out5
):
    answers = {PATH_OUTPUT_LEVEL: out_answer}
    if out5_answer is not NOT_ASKED:
        answers[PATH_OUTPUT_LEVEL_OUT5] = out5_answer
    client = _Client(answers)

    await _async_select_output_paths(_entry("KH 750"), client)

    assert client.installed_aliases == expected_aliases
    assert (PATH_OUTPUT_LEVEL_OUT5 in client.asked) is asks_out5


async def test_a_model_without_out5_is_never_probed():
    client = _Client({})

    await _async_select_output_paths(_entry("KH 120 II"), client)

    assert client.asked == []
    assert client.installed_aliases is None
