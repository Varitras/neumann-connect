"""The guarantees export_file.py documents, each with a test that can fail.

A device-supplied name never leaves the export folder, two speakers whose
masked serials collide do not overwrite each other, and a failed write leaves
the previous export in place without a stray temporary file.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import export_file
from custom_components.neumann_kh.export_file import EXPORT_DIR_NAME, async_write_export


def _hass(config_dir):
    async def _run(function, *args):
        return function(*args)

    return SimpleNamespace(
        config=SimpleNamespace(path=lambda *parts: os.path.join(config_dir, *parts)),
        async_add_executor_job=_run,
    )


async def test_a_device_supplied_name_stays_inside_the_export_folder(tmp_path):
    path = await async_write_export(_hass(tmp_path), "backup", "../../escape", {"a": 1})

    assert os.path.dirname(path) == os.path.join(tmp_path, EXPORT_DIR_NAME)
    assert os.listdir(tmp_path) == [EXPORT_DIR_NAME]


async def test_colliding_masked_serials_get_separate_files(tmp_path):
    hass = _hass(tmp_path)

    first = await async_write_export(hass, "backup", "***123", {"speaker": 1}, "entry_a")
    second = await async_write_export(hass, "backup", "***123", {"speaker": 2}, "entry_b")

    assert first != second
    with open(first, encoding="utf-8") as file:
        assert json.load(file) == {"speaker": 1}


async def test_a_failed_write_keeps_the_previous_export_and_no_temp_file(tmp_path, monkeypatch):
    hass = _hass(tmp_path)
    path = await async_write_export(hass, "backup", "SIM", {"version": "old"})

    def _broken_dump(*args, **kwargs):
        raise OSError("disk full (test)")

    monkeypatch.setattr(export_file.json, "dump", _broken_dump)
    with pytest.raises(OSError):
        await async_write_export(hass, "backup", "SIM", {"version": "new"})

    with open(path, encoding="utf-8") as file:
        assert json.load(file) == {"version": "old"}
    assert os.listdir(os.path.dirname(path)) == [os.path.basename(path)]
