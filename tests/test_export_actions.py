"""Tests for the restore bookkeeping.

Uses fakes rather than a Home Assistant instance: what matters here is how a
device answer is counted and what reaches the coordinator, and neither needs a
running integration.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh import export_actions
from custom_components.neumann_kh._util import build_nested, deep_merge
from custom_components.neumann_kh.backup_export import (
    restorable_paths_for_model,
)
from custom_components.neumann_kh.const import CONF_MODEL, CONF_SERIAL
from custom_components.neumann_kh.export_actions import async_run_restore

_KH_120_II = "KH 120 II"


class _FakeClient:
    """Echoes what it is given, except for the paths in `answers_none`."""

    def __init__(self, answers_none: set[tuple[str, ...]]) -> None:
        self.answers_none = answers_none
        self.written: list[tuple[tuple[str, ...], Any]] = []

    async def set(self, path: tuple[str, ...], value: Any) -> Any:
        self.written.append((path, value))
        if path in self.answers_none:
            # Device replied, but not for this path - so nothing is confirmed.
            return None
        return value


class _FakeCoordinator:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.applied: list[tuple[tuple[str, ...], Any]] = []

    def apply_confirmed_values(self, values: list[tuple[tuple[str, ...], Any]]) -> None:
        self.applied.extend(values)


class _FakeEntry:
    def __init__(self, model: str) -> None:
        self.data = {CONF_MODEL: model}
        self.title = "Speaker"


class _FakeConfig:
    language = "en"


class _FakeHass:
    config = _FakeConfig()


@pytest.fixture(autouse=True)
def _no_notification(monkeypatch):
    """The notification needs a real hass; the counting under test does not."""
    monkeypatch.setattr(export_actions, "_notify", lambda *args, **kwargs: None)


def _backup_covering(model: str) -> dict[str, Any]:
    """A backup that holds a value for every restorable path."""
    values: dict[str, Any] = {}
    for path in restorable_paths_for_model(model):
        deep_merge(values, build_nested(path, 1))
    return {"values": values}


async def test_unconfirmed_value_is_skipped_not_counted_as_adjusted():
    """A None answer confirms nothing.

    Counting it as adjusted misreports it, and passing None on to the
    coordinator drops the entity to unknown - for a slow-polled path that
    then sticks in the cache until the next slow cycle.
    """
    paths = restorable_paths_for_model(_KH_120_II)
    unconfirmed = paths[0]

    client = _FakeClient(answers_none={unconfirmed})
    coordinator = _FakeCoordinator(client)

    written, adjusted, skipped = await async_run_restore(
        _FakeHass(), _FakeEntry(_KH_120_II), coordinator, backup=_backup_covering(_KH_120_II)
    )

    applied_paths = [path for path, _ in coordinator.applied]
    assert unconfirmed not in applied_paths, "None reached the coordinator"
    assert not any(value is None for _, value in coordinator.applied)

    assert skipped == 1
    assert adjusted == 0, "an unconfirmed value must not count as adjusted"
    assert written == len(paths) - 1


async def test_confirmed_values_still_reach_the_coordinator():
    """Guard against the fix above swallowing the normal case."""
    paths = restorable_paths_for_model(_KH_120_II)
    client = _FakeClient(answers_none=set())
    coordinator = _FakeCoordinator(client)

    written, adjusted, skipped = await async_run_restore(
        _FakeHass(), _FakeEntry(_KH_120_II), coordinator, backup=_backup_covering(_KH_120_II)
    )

    assert written == len(paths)
    assert (adjusted, skipped) == (0, 0)
    assert len(coordinator.applied) == len(paths)


# --- Backup bookkeeping -----------------------------------------------------


class _FakeEntryWithSerial(_FakeEntry):
    def __init__(self, model: str = _KH_120_II) -> None:
        super().__init__(model)
        self.data = {**self.data, CONF_SERIAL: "SIM0001234"}
        self.entry_id = "entry1"


async def _run_backup(hass, monkeypatch, values, write=None):
    saved: list[Any] = []
    written: list[Any] = []

    async def _build(client, model):
        return values

    async def _save(hass_, serial, record):
        saved.append(record)

    async def _write(hass_, kind, masked, record, entry_id):
        written.append(record)
        if write is not None:
            return write()
        return "/config/neumann_kh/backup.json"

    monkeypatch.setattr(export_actions, "async_build_backup", _build)
    monkeypatch.setattr(export_actions.storage, "async_save_backup", _save)
    monkeypatch.setattr(export_actions, "async_write_export", _write)
    monkeypatch.setattr(export_actions, "_notify_written", lambda *a, **k: None)

    return saved, written


async def test_an_empty_backup_does_not_replace_the_last_good_one(monkeypatch):
    """A run that read nothing is a failed backup, not an empty one.

    Storing it would swap the last usable snapshot for a file that can restore
    nothing, while the notification still said "saved".
    """
    saved, _ = await _run_backup(None, monkeypatch, values={})

    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(
            _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
        )

    assert err.value.translation_key == "backup_empty"
    assert not saved, "an empty backup was stored anyway"


async def test_a_failed_file_write_leaves_the_store_untouched(monkeypatch):
    """Restore reads the store, so it must not move ahead of the file.

    Otherwise the store points at a snapshot the user cannot see, while the
    file on disk is the older one.
    """
    def _boom():
        raise OSError("disk full")

    saved, written = await _run_backup(
        None, monkeypatch, values={"device": {"name": "x"}}, write=_boom
    )

    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(
            _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
        )

    assert err.value.translation_key == "backup_failed"
    assert written, "the file write was not even attempted"
    assert not saved, "the store was updated even though the file failed"


async def test_a_good_backup_reaches_both(monkeypatch):
    saved, written = await _run_backup(
        None, monkeypatch, values={"device": {"name": "x"}}
    )

    path = await export_actions.async_run_backup(
        _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
    )

    assert path.endswith("backup.json")
    assert len(saved) == 1
    assert len(written) == 1


async def test_a_failed_discovery_file_write_leaves_the_store_untouched(monkeypatch):
    """The discovery run had the same ordering problem as the backup one.

    Fixing only the backup left its sibling two functions below untouched -
    same structure, same store-before-file, same unwrapped OSError.
    """
    saved: list[Any] = []
    written: list[Any] = []

    async def _discover(client, model):
        return {"values": {"device": {"name": "x"}}}

    async def _save(hass_, serial, record):
        saved.append(record)

    async def _write(hass_, kind, masked, record, entry_id):
        written.append(record)
        raise OSError("disk full")

    monkeypatch.setattr(export_actions, "async_discover_all_values", _discover)
    monkeypatch.setattr(export_actions.storage, "async_save_discovery", _save)
    monkeypatch.setattr(export_actions, "async_write_export", _write)
    monkeypatch.setattr(export_actions, "_notify_written", lambda *a, **k: None)

    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_discovery(
            _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
        )

    assert err.value.translation_key == "discovery_failed"
    assert written, "the file write was not even attempted"
    assert not saved, "the store was updated even though the file failed"
