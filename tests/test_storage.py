"""Tests for the three persistent stores.

These outlive a config entry and hold the backup a restore reads, so what
matters is that one serial's entry never overwrites another's and that a
device without a serial cannot write at all - the guards for both were
uncovered before this file existed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import storage


async def test_a_name_survives_a_round_trip(hass):
    await storage.async_remember_name(hass, "SIM0001234", "Left")

    assert await storage.async_get_remembered_name(hass, "SIM0001234") == "Left"


async def test_a_backup_survives_a_round_trip(hass):
    backup = {"model": "KH 120 II", "values": {"audio": {"out": {"level": 100.0}}}}

    await storage.async_save_backup(hass, "SIM0001234", backup)

    assert await storage.async_get_backup(hass, "SIM0001234") == backup


async def test_a_second_speaker_does_not_replace_the_first(hass):
    """Every store is one file for all speakers, keyed by serial.

    A save that wrote the whole mapping instead of merging into it would lose
    the other speakers' backups - and nothing would report it until someone
    tried to restore one.
    """
    await storage.async_save_backup(hass, "SIM0001234", {"model": "KH 120 II"})
    await storage.async_save_backup(hass, "SIM0007500", {"model": "KH 750"})

    assert await storage.async_get_backup(hass, "SIM0001234") == {"model": "KH 120 II"}
    assert await storage.async_get_backup(hass, "SIM0007500") == {"model": "KH 750"}


async def test_saving_the_same_serial_twice_replaces_it(hass):
    await storage.async_save_backup(hass, "SIM0001234", {"model": "old"})
    await storage.async_save_backup(hass, "SIM0001234", {"model": "new"})

    assert await storage.async_get_backup(hass, "SIM0001234") == {"model": "new"}


@pytest.mark.parametrize("empty", ["", None])
async def test_a_device_without_a_serial_writes_nothing(hass, empty):
    """Entries created before serials were stored have none.

    Writing those under a shared empty key would let unrelated speakers read
    each other's backup.
    """
    await storage.async_remember_name(hass, empty, "Nameless")
    await storage.async_save_backup(hass, empty, {"model": "KH 120 II"})
    await storage.async_save_discovery(hass, empty, {"known_paths": {}})

    assert await storage.async_get_remembered_name(hass, empty) is None
    assert await storage.async_get_backup(hass, empty) is None


async def test_an_unknown_serial_reads_as_missing(hass):
    await storage.async_save_backup(hass, "SIM0001234", {"model": "KH 120 II"})

    assert await storage.async_get_backup(hass, "SIM0009999") is None


async def test_the_stores_do_not_share_a_key(hass):
    """Three stores, three files - a name must not surface as a backup."""
    await storage.async_remember_name(hass, "SIM0001234", "Left")
    await storage.async_save_discovery(hass, "SIM0001234", {"known_paths": {"a": 1}})

    assert await storage.async_get_backup(hass, "SIM0001234") is None
    assert await storage.async_get_remembered_name(hass, "SIM0001234") == "Left"
