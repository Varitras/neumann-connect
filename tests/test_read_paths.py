"""The one loop that reads a list of paths for the backup and the discovery.

Both used to carry their own copy. What it must guarantee, per error kind:
a path the device rejects is skipped, a lost connection aborts the run (a
half-read snapshot would replace the last good one), and a bug on one path is
logged and skipped instead of failing the whole run.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import backup_export
from custom_components.neumann_kh.backup_export import async_build_backup, async_read_paths
from custom_components.neumann_kh.const import PATH_METER_INPUT_LEVEL, PATH_OUTPUT_LEVEL
from custom_components.neumann_kh.ssc_client import SSCConnectionError, SSCDeviceError

_A = ("audio", "out", "level")
_B = ("audio", "out", "mute")
_C = ("device", "name")


class _Timeout(Exception):
    pass


class _Client:
    def __init__(self, answers) -> None:
        self.answers = answers
        self.asked: list[tuple[str, ...]] = []

    async def get(self, path):
        self.asked.append(path)
        answer = self.answers.get(path)
        if isinstance(answer, Exception):
            raise answer
        return answer


async def test_a_rejected_path_is_skipped():
    client = _Client({_A: 80.0, _B: SSCDeviceError("404"), _C: "Left"})
    result = await async_read_paths(client, [_A, _B, _C], _Timeout)
    assert result == {"audio": {"out": {"level": 80.0}}, "device": {"name": "Left"}}


async def test_a_lost_connection_aborts_the_run():
    client = _Client({_A: 80.0, _B: SSCConnectionError("gone"), _C: "Left"})
    with pytest.raises(SSCConnectionError):
        await async_read_paths(client, [_A, _B, _C], _Timeout)
    assert _C not in client.asked


async def test_a_bug_on_one_path_is_logged_and_skipped(caplog):
    client = _Client({_A: RuntimeError("bug"), _C: "Left"})
    with caplog.at_level(logging.ERROR):
        result = await async_read_paths(client, [_A, _C], _Timeout)
    assert result == {"device": {"name": "Left"}}
    assert any("audio" in record.getMessage() for record in caplog.records)


async def test_the_run_stops_at_the_deadline(monkeypatch):
    monkeypatch.setattr(backup_export, "DEVICE_ACTION_TIMEOUT_SECONDS", -1)
    client = _Client({_A: 80.0})
    with pytest.raises(_Timeout):
        await async_read_paths(client, [_A], _Timeout)
    assert client.asked == []


async def test_the_backup_leaves_live_readings_out():
    client = _Client({PATH_OUTPUT_LEVEL: 80.0, PATH_METER_INPUT_LEVEL: [-40.0]})
    await async_build_backup(client, "KH 120 II")
    assert PATH_OUTPUT_LEVEL in client.asked
    assert PATH_METER_INPUT_LEVEL not in client.asked
