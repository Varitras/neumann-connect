"""The connection test every config flow asks before it stores anything.

The flow tests patch it away, so its own guards - a missing vendor field is
not a failure, a timeout is reported as one, odd identity answers are coerced
- are pinned here against a fake client.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import config_flow
from custom_components.neumann_kh.const import (
    MAX_PARALLEL_IDENTITY_QUERIES,
    PATH_IDENTITY_PRODUCT,
    PATH_IDENTITY_SERIAL,
    PATH_IDENTITY_VENDOR,
    PATH_IDENTITY_VERSION,
)
from custom_components.neumann_kh.discovery import DiscoveredSpeaker
from custom_components.neumann_kh.ssc_client import (
    SSCConnectionError,
    SSCDeviceError,
    SSCTimeoutError,
)

_SPEAKER = {
    PATH_IDENTITY_PRODUCT: "KH 120 II",
    PATH_IDENTITY_SERIAL: "SIM0001234",
    PATH_IDENTITY_VERSION: "2_1_2",
    PATH_IDENTITY_VENDOR: "Georg Neumann GmbH",
}


class _Client:
    closed = 0

    def __init__(self, answers, *args, **kwargs) -> None:
        self.answers = answers

    async def get(self, path):
        answer = self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        _Client.closed += 1


@pytest.fixture
def speaker(monkeypatch):
    answers = dict(_SPEAKER)
    monkeypatch.setattr(config_flow, "SSCClient", lambda *args, **kwargs: _Client(answers))
    _Client.closed = 0
    return answers


async def _identity():
    return await config_flow._async_test_connection("fe80::1", 45, "eth0")


async def test_a_device_without_a_vendor_field_still_passes(speaker):
    speaker[PATH_IDENTITY_VENDOR] = SSCDeviceError("rejected", code=404)

    identity = await _identity()

    assert identity.error_key is None
    assert identity.vendor is None
    assert identity.serial == "SIM0001234"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SSCTimeoutError("t"), "timeout"),
        (SSCConnectionError("c"), "cannot_connect"),
        (SSCDeviceError("x", code=400), "cannot_connect"),
    ],
)
async def test_a_failed_identity_read_is_reported_and_closes_the_client(speaker, error, expected):
    speaker[PATH_IDENTITY_SERIAL] = error

    identity = await _identity()

    assert identity.error_key == expected
    assert _Client.closed == 1


async def test_odd_identity_answers_are_coerced(speaker):
    speaker[PATH_IDENTITY_PRODUCT] = ["KH 120 II"]
    speaker[PATH_IDENTITY_SERIAL] = " SIM0001234 "
    speaker[PATH_IDENTITY_VENDOR] = True

    identity = await _identity()

    assert identity.product is None
    assert identity.serial == "SIM0001234"
    assert identity.vendor is None


async def test_every_candidate_is_identified_and_at_most_a_few_at_once(monkeypatch):
    running = 0
    peak = 0

    async def _test_connection(host, port, interface):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0)
        running -= 1
        return config_flow.DeviceIdentity(serial=host)

    monkeypatch.setattr(config_flow, "_async_test_connection", _test_connection)
    speakers = [
        DiscoveredSpeaker(mdns_name=f"s{i}._ssc._tcp.local.", host=f"fe80::{i}", port=45)
        for i in range(MAX_PARALLEL_IDENTITY_QUERIES * 2)
    ]

    results = await config_flow._async_identify_all(speakers)

    assert [(identity.serial, speaker.host) for identity, speaker in results] == [
        (speaker.host, speaker.host) for speaker in speakers
    ]
    assert 1 < peak <= MAX_PARALLEL_IDENTITY_QUERIES
