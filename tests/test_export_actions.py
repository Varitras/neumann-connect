"""Tests for the restore bookkeeping.

Uses fakes rather than a Home Assistant instance: what matters here is how a
device answer is counted and what reaches the coordinator, and neither needs a
running integration.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh._util import build_nested, deep_merge  # noqa: E402
from custom_components.neumann_kh.backup_export import (  # noqa: E402
    restorable_paths_for_model,
)
from custom_components.neumann_kh.const import CONF_MODEL  # noqa: E402
from custom_components.neumann_kh import export_actions  # noqa: E402
from custom_components.neumann_kh.export_actions import async_run_restore  # noqa: E402

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
