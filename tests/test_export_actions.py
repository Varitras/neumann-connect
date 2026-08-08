"""Tests for the restore bookkeeping.

Uses fakes rather than a Home Assistant instance: what matters here is how a
device answer is counted and what reaches the coordinator, and neither needs a
running integration.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh import backup_export, export_actions
from custom_components.neumann_kh._util import build_nested, deep_merge
from custom_components.neumann_kh.backup_export import (
    restorable_paths_for_model,
)
from custom_components.neumann_kh.const import CONF_MODEL, CONF_SERIAL
from custom_components.neumann_kh.export_actions import async_run_restore
from custom_components.neumann_kh.ssc_client import SSCDeviceError

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


def _fakes():
    """Build the fakes outside the pytest.raises block.

    Constructed inside it, a constructor that started raising would satisfy
    the expectation and the test would pass for the wrong reason.
    """
    return _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())


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

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(hass, entry, client)

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

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(hass, entry, client)

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

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_discovery(hass, entry, client)

    assert err.value.translation_key == "discovery_failed"
    assert written, "the file write was not even attempted"
    assert not saved, "the store was updated even though the file failed"


async def test_a_backup_without_any_restorable_value_is_refused(monkeypatch):
    """"Read something" is not the bar - "can restore something" is.

    A run that only picked up a diagnostic value would otherwise count as a
    success and replace the last usable snapshot with one that restores
    nothing.
    """
    saved, _ = await _run_backup(
        None,
        monkeypatch,
        # Read-only diagnostics, not a single path the restore may write.
        values={"device": {"identity": {"hw_version": "1.0"}}},
    )

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(hass, entry, client)

    assert err.value.translation_key == "backup_empty"
    assert not saved, "a backup that restores nothing was stored anyway"


async def test_a_backup_with_one_restorable_value_is_kept(monkeypatch):
    """Guard against the check above rejecting a partial but usable backup."""
    saved, _ = await _run_backup(
        None, monkeypatch, values={"device": {"name": "Speaker"}}
    )

    await export_actions.async_run_backup(
        _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
    )

    assert len(saved) == 1


async def test_a_failing_store_is_reported_readably(monkeypatch):
    """The file is already written by then; the error must still be legible."""
    async def _boom(hass_, serial, record):
        raise OSError("store is locked")

    await _run_backup(None, monkeypatch, values={"device": {"name": "x"}})
    monkeypatch.setattr(export_actions.storage, "async_save_backup", _boom)

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_backup(hass, entry, client)

    assert err.value.translation_key == "backup_failed"


async def test_a_discovery_that_read_nothing_does_not_replace_the_last_one(monkeypatch):
    """The backup gained this guard; its sibling below it did not.

    Two empty trees used to overwrite both the file and the store and still
    report success - the same shape of bug the backup check was added for.
    """
    saved: list[Any] = []
    written: list[Any] = []

    async def _discover(client, model):
        return {"known_paths": {}, "schema_limits": {}}

    monkeypatch.setattr(export_actions, "async_discover_all_values", _discover)
    monkeypatch.setattr(
        export_actions.storage, "async_save_discovery",
        lambda *a, **k: saved.append(a),
    )
    monkeypatch.setattr(
        export_actions, "async_write_export", lambda *a, **k: written.append(a),
    )
    monkeypatch.setattr(export_actions, "_notify_written", lambda *a, **k: None)

    hass, entry, client = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_run_discovery(hass, entry, client)

    assert err.value.translation_key == "discovery_empty"
    assert not written, "an empty discovery was written to a file anyway"
    assert not saved, "an empty discovery reached the store anyway"


async def test_a_discovery_with_only_known_paths_still_goes_through(monkeypatch):
    """Counter-check: osc/schema is rejected by most firmware.

    If the guard required both parts it would refuse every normal run, which
    is exactly the failure the check above must not turn into.
    """
    written: list[Any] = []

    async def _discover(client, model):
        return {"known_paths": {"device": {"name": "x"}}, "schema_limits": {}}

    async def _write(hass_, kind, masked, record, entry_id):
        written.append(record)
        return "/config/neumann_kh/discovery.json"

    async def _save(hass_, serial, record):
        return None

    monkeypatch.setattr(export_actions, "async_discover_all_values", _discover)
    monkeypatch.setattr(export_actions.storage, "async_save_discovery", _save)
    monkeypatch.setattr(export_actions, "async_write_export", _write)
    monkeypatch.setattr(export_actions, "_notify_written", lambda *a, **k: None)

    path = await export_actions.async_run_discovery(
        _FakeHass(), _FakeEntryWithSerial(), _FakeClient(answers_none=set())
    )

    assert path.endswith("discovery.json")
    assert len(written) == 1


async def test_a_backup_without_restorable_values_is_refused_at_restore(monkeypatch):
    """The write side got this check; the read side kept accepting anything.

    A snapshot from before the backup guard existed holds identity and
    diagnostics only. It passed the "values is not empty" test, wrote nothing,
    and still reported a successful restore.
    """
    stored = {
        "model": _KH_120_II,
        "serial": export_actions.mask_serial("SIM0001234"),
        "values": {"device": {"identity": {"product": _KH_120_II}}},
    }

    async def _get_backup(hass_, serial):
        return stored

    monkeypatch.setattr(export_actions.storage, "async_get_backup", _get_backup)

    hass, entry, _ = _fakes()
    with pytest.raises(HomeAssistantError) as err:
        await export_actions.async_check_restorable(hass, entry)

    assert err.value.translation_key == "restore_nothing_to_write"


async def test_a_backup_with_one_restorable_value_is_accepted(monkeypatch):
    """Counter-check: the guard must not raise the bar to "complete"."""
    values: dict[str, Any] = {}
    deep_merge(values, build_nested(restorable_paths_for_model(_KH_120_II)[0], 1))
    stored = {
        "model": _KH_120_II,
        "serial": export_actions.mask_serial("SIM0001234"),
        "values": values,
    }

    async def _get_backup(hass_, serial):
        return stored

    monkeypatch.setattr(export_actions.storage, "async_get_backup", _get_backup)

    assert await export_actions.async_check_restorable(
        _FakeHass(), _FakeEntryWithSerial()
    ) is stored


class _SlowClient(_FakeClient):
    """Answers, but slowly enough that the run runs out of time."""

    async def set(self, path, value):
        await asyncio.sleep(0.05)
        return await super().set(path, value)


async def test_a_restore_that_runs_out_of_time_reports_how_far_it_got(monkeypatch):
    """Stopping has to keep the partial progress, not discard it.

    Wrapping the loop in wait_for() would cancel inside a set(): the values
    already confirmed would never reach the coordinator and the user would see
    a bare abort instead of a count, on a speaker that is half rewritten. So
    the limit is checked between paths.
    """
    monkeypatch.setattr(export_actions, "DEVICE_ACTION_TIMEOUT_SECONDS", 0.1)

    client = _SlowClient(answers_none=set())
    coordinator = _FakeCoordinator(client)

    with pytest.raises(HomeAssistantError) as err:
        await async_run_restore(
            _FakeHass(), _FakeEntry(_KH_120_II), coordinator, _backup_covering(_KH_120_II)
        )

    assert err.value.translation_key == "restore_timed_out"
    # Some paths made it, and what the device confirmed reached the entities.
    assert client.written, "the restore stopped before writing anything at all"
    assert coordinator.applied, "confirmed values were dropped on the way out"
    assert len(client.written) < len(restorable_paths_for_model(_KH_120_II))


async def test_a_backup_that_runs_out_of_time_saves_nothing(monkeypatch):
    """A partial snapshot is worse than none - it looks complete."""
    monkeypatch.setattr(backup_export, "DEVICE_ACTION_TIMEOUT_SECONDS", 0.1)

    class _SlowReader:  # skipcq: PYL-R0201 - a stand-in, not a design
        async def get(self, path):
            await asyncio.sleep(0.05)
            return 1

    with pytest.raises(backup_export.BackupTimeoutError):
        await backup_export.async_build_backup(_SlowReader(), _KH_120_II)


async def test_a_restore_the_device_refuses_entirely_is_not_a_success():
    """Announcing "restored" after writing nothing is worse than an error.

    The user walks away believing the speaker was rewritten. Every path being
    refused means the backup does not fit this model or firmware.
    """

    class _RefusingClient(_FakeClient):
        async def set(self, path, value):
            raise SSCDeviceError("not writable here")

    client = _RefusingClient(answers_none=set())
    coordinator = _FakeCoordinator(client)

    with pytest.raises(HomeAssistantError) as err:
        await async_run_restore(
            _FakeHass(), _FakeEntry(_KH_120_II), coordinator, _backup_covering(_KH_120_II)
        )

    assert err.value.translation_key == "restore_nothing_written"
    assert not coordinator.applied, "nothing was confirmed, so nothing may be applied"
