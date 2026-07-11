"""Tests für die Coordinator-Logik: Poll-Aufteilung, Slow-Cache, Pending-Flag.

Enthält insbesondere die Regressionstests für den Rückspringer-Bug
(v1.15.1): vom Gerät bestätigte Werte auf Slow-Pfaden dürfen vom nächsten
schnellen Zyklus nicht mit dem veralteten Cache überschrieben werden.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.neumann_kh.const import (
    PATH_DEVICE_NAME,
    PATH_OUTPUT_MUTE,
    SLOW_POLL_PATHS,
)
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.ssc_client import SSCConnectionError, SSCDeviceError


class FakeClient:
    """Client-Ersatz: liefert Werte aus einem Dict, Fehler steuerbar."""

    def __init__(self, values: dict[tuple[str, ...], Any]) -> None:
        self.values = values
        self.fail_connection = False
        self.rejected_paths: set[tuple[str, ...]] = set()
        self.priority_waiting = asyncio.Event()

    async def get(self, path: tuple[str, ...], priority: bool = False) -> Any:
        if self.fail_connection:
            raise SSCConnectionError("Gerät offline (Test)")
        if path in self.rejected_paths:
            raise SSCDeviceError("Pfad abgelehnt (Test)")
        return self.values.get(path)


@pytest.fixture
def fake_client() -> FakeClient:
    values: dict[tuple[str, ...], Any] = {
        PATH_OUTPUT_MUTE: False,  # schneller Pfad
        PATH_DEVICE_NAME: "Links",  # langsamer Pfad
    }
    return FakeClient(values)


@pytest.fixture
def coordinator(hass, fake_client) -> NeumannKHCoordinator:
    coord = NeumannKHCoordinator(hass, fake_client, "test", model="KH 120 II")
    # Kein automatisches Nach-Scheduling im Test (verhindert hängende Timer).
    coord.update_interval = None
    return coord


def _value(coord: NeumannKHCoordinator, path: tuple[str, ...]) -> Any:
    return coord.value(path)


async def test_first_cycle_includes_slow_paths(coordinator, fake_client):
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_fast_cycle_serves_slow_values_from_cache(coordinator, fake_client):
    await coordinator.async_refresh()  # Zyklus 0: slow inklusive
    # Gerät ändert den langsamen Wert extern - schneller Zyklus darf das
    # noch nicht sehen (kommt erst mit dem nächsten Slow-Poll).
    fake_client.values[PATH_DEVICE_NAME] = "Umbenannt"
    await coordinator.async_refresh()  # Zyklus 1: fast
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_confirmed_slow_value_survives_fast_cycle(coordinator, fake_client):
    """Regression v1.15.1: kein Rückspringer nach Nutzeraktion auf Slow-Pfad."""
    await coordinator.async_refresh()  # Zyklus 0
    # Nutzer benennt das Gerät um, Gerät bestätigt.
    coordinator.apply_confirmed_value(PATH_DEVICE_NAME, "Neuer Name")
    fake_client.values[PATH_DEVICE_NAME] = "Neuer Name"  # Gerätezustand
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"

    await coordinator.async_refresh()  # Zyklus 1: fast, mischt Cache ein
    # VOR dem Fix sprang der Wert hier auf "Links" zurück.
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"


async def test_confirmed_fast_value_not_cached_as_slow(coordinator, fake_client):
    """Gegenprobe: Fast-Pfade laufen nicht durch den Slow-Cache."""
    await coordinator.async_refresh()
    coordinator.apply_confirmed_value(PATH_OUTPUT_MUTE, True)
    assert _value(coordinator, PATH_OUTPUT_MUTE) is True
    # Gerät meldet inzwischen wieder False - der frische Poll-Wert muss gewinnen.
    fake_client.values[PATH_OUTPUT_MUTE] = False
    await coordinator.async_refresh()
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False


async def test_failed_slow_cycle_is_retried_next_cycle(coordinator, fake_client):
    """Pending-Flag: fällt der Slow-Zyklus aus, holt der nächste ihn nach."""
    fake_client.fail_connection = True
    await coordinator.async_refresh()  # Zyklus 0 (slow) scheitert
    assert not coordinator.last_update_success

    fake_client.fail_connection = False
    fake_client.values[PATH_DEVICE_NAME] = "Nach Reconnect"
    await coordinator.async_refresh()  # Zyklus 1: eigentlich fast, holt slow nach
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_DEVICE_NAME) == "Nach Reconnect"


async def test_slow_values_refresh_on_next_slow_cycle(coordinator, fake_client):
    from custom_components.neumann_kh.const import SLOW_POLL_EVERY_N_CYCLES

    await coordinator.async_refresh()  # Zyklus 0: slow
    fake_client.values[PATH_DEVICE_NAME] = "Später geändert"
    for _ in range(SLOW_POLL_EVERY_N_CYCLES - 1):
        await coordinator.async_refresh()  # nur fast
        assert _value(coordinator, PATH_DEVICE_NAME) == "Links"
    await coordinator.async_refresh()  # nächster Slow-Zyklus
    assert _value(coordinator, PATH_DEVICE_NAME) == "Später geändert"


async def test_rejected_path_does_not_break_cycle(coordinator, fake_client):
    fake_client.rejected_paths.add(PATH_DEVICE_NAME)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False
    assert _value(coordinator, PATH_DEVICE_NAME) is None


async def test_all_slow_paths_registered_in_slow_set(coordinator):
    """Absicherung des Membership-Tests von apply_confirmed_value()."""
    for path in SLOW_POLL_PATHS:
        assert path in coordinator._slow_path_set  # noqa: SLF001
