"""Tests for the coordinator logic: poll split, slow cache, pending flag.

In particular contains the regression tests for the value-snapping-back bug
(v1.15.1): device-confirmed values on slow paths must not be overwritten by
the next fast cycle with the stale cache.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.neumann_kh.const import (
    PATH_DEVICE_NAME,
    PATH_OUT1_LEVEL,
    PATH_OUTPUT_MUTE,
    PATH_STANDBY_COUNTDOWN,
    SLOW_POLL_PATHS,
)
from custom_components.neumann_kh.coordinator import NeumannKHCoordinator
from custom_components.neumann_kh.ssc_client import SSCConnectionError, SSCDeviceError


class FakeClient:
    """Client replacement: returns values from a dict, errors controllable."""

    def __init__(self, values: dict[tuple[str, ...], Any]) -> None:
        self.values = values
        self.fail_connection = False
        self.rejected_paths: set[tuple[str, ...]] = set()
        self.asked: list[tuple[str, ...]] = []

    async def get(self, path: tuple[str, ...]) -> Any:
        self.asked.append(path)
        if self.fail_connection:
            raise SSCConnectionError("device offline (test)")
        if path in self.rejected_paths:
            raise SSCDeviceError("path rejected (test)")
        return self.values.get(path)


@pytest.fixture
def fake_client() -> FakeClient:
    values: dict[tuple[str, ...], Any] = {
        PATH_OUTPUT_MUTE: False,  # fast path
        PATH_DEVICE_NAME: "Links",  # slow path
    }
    return FakeClient(values)


@pytest.fixture
def coordinator(hass, fake_client) -> NeumannKHCoordinator:
    coord = NeumannKHCoordinator(hass, fake_client, "test", model="KH 120 II")
    # No automatic re-scheduling in the test (prevents hanging timers).
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
    await coordinator.async_refresh()  # cycle 0: slow included
    # Device changes the slow value externally - the fast cycle must not
    # see it yet (only comes with the next slow poll).
    fake_client.values[PATH_DEVICE_NAME] = "Umbenannt"
    await coordinator.async_refresh()  # cycle 1: fast
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_confirmed_slow_value_survives_fast_cycle(coordinator, fake_client):
    """Regression v1.15.1: no snapping back after user action on a slow path."""
    await coordinator.async_refresh()  # cycle 0
    # User renames the device, device confirms.
    coordinator.apply_confirmed_value(PATH_DEVICE_NAME, "Neuer Name")
    fake_client.values[PATH_DEVICE_NAME] = "Neuer Name"  # device state
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"

    await coordinator.async_refresh()  # cycle 1: fast, mixes in cache
    # BEFORE the fix the value snapped back to "Links" here.
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name"


async def test_confirmed_fast_value_not_cached_as_slow(coordinator, fake_client):
    """Counter-check: fast paths do not go through the slow cache."""
    await coordinator.async_refresh()
    coordinator.apply_confirmed_value(PATH_OUTPUT_MUTE, True)
    assert _value(coordinator, PATH_OUTPUT_MUTE) is True
    # Device meanwhile reports False again - the fresh poll value must win.
    fake_client.values[PATH_OUTPUT_MUTE] = False
    await coordinator.async_refresh()
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False


async def test_failed_slow_cycle_is_retried_next_cycle(coordinator, fake_client):
    """Pending flag: if the slow cycle fails, the next one catches it up."""
    fake_client.fail_connection = True
    await coordinator.async_refresh()  # cycle 0 (slow) fails
    assert not coordinator.last_update_success

    fake_client.fail_connection = False
    fake_client.values[PATH_DEVICE_NAME] = "Nach Reconnect"
    await coordinator.async_refresh()  # cycle 1: actually fast, catches up slow
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_DEVICE_NAME) == "Nach Reconnect"


async def test_slow_values_refresh_on_next_slow_cycle(coordinator, fake_client):
    from custom_components.neumann_kh.const import SLOW_POLL_EVERY_N_CYCLES

    await coordinator.async_refresh()  # cycle 0: slow
    fake_client.values[PATH_DEVICE_NAME] = "Changed later"
    for _ in range(SLOW_POLL_EVERY_N_CYCLES - 1):
        await coordinator.async_refresh()  # fast only
        assert _value(coordinator, PATH_DEVICE_NAME) == "Links"
    await coordinator.async_refresh()  # next slow cycle
    assert _value(coordinator, PATH_DEVICE_NAME) == "Changed later"


async def test_rejected_path_does_not_break_cycle(coordinator, fake_client):
    fake_client.rejected_paths.add(PATH_DEVICE_NAME)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _value(coordinator, PATH_OUTPUT_MUTE) is False
    assert _value(coordinator, PATH_DEVICE_NAME) is None


async def test_all_slow_paths_registered_in_slow_set(coordinator):
    """Safeguard for the membership test of apply_confirmed_value()."""
    for path in SLOW_POLL_PATHS:
        assert path in coordinator._slow_path_set


async def test_invalidate_and_refresh_rereads_the_slow_paths(coordinator, fake_client):
    """A factory reset rewrites everything, so every cached value is stale.

    Without dropping the slow cache the rarely polled entities - the device
    name among them - would keep showing pre-reset settings for up to five
    minutes while the device had already moved on.
    """
    await coordinator.async_refresh()  # cycle 0: slow paths cached
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"

    # The device is reset behind our back.
    fake_client.values[PATH_DEVICE_NAME] = "Factory default"

    await coordinator.async_invalidate_and_refresh()
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) == "Factory default"


async def test_a_slow_value_unanswered_after_a_reset_is_not_shown_from_before_it(
    coordinator, fake_client
):
    """The re-read above overwrites every path that answers; this one does not."""
    await coordinator.async_refresh()  # cycle 0: slow paths cached
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"

    fake_client.rejected_paths.add(PATH_DEVICE_NAME)
    await coordinator.async_invalidate_and_refresh()
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) is None


async def test_a_plain_refresh_still_uses_the_slow_cache(coordinator, fake_client):
    """Guard against the invalidation above turning every cycle into a slow one."""
    await coordinator.async_refresh()  # cycle 0: slow
    fake_client.values[PATH_DEVICE_NAME] = "Changed later"

    await coordinator.async_refresh()  # fast cycle

    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"


async def test_one_failed_slow_path_does_not_wipe_the_others(coordinator, fake_client):
    """The cache used to be emptied and rebuilt from this round's answers only.

    A single path that happened to be rejected therefore lost its value
    everywhere - the entity dropped to unknown and stayed there until the next
    slow cycle, up to five minutes later, over one missed answer.
    """
    await coordinator.async_refresh()  # cycle 0: slow, everything cached
    assert _value(coordinator, PATH_DEVICE_NAME) == "Links"

    # The device rejects just this one path on the next slow round.
    fake_client.rejected_paths.add(PATH_DEVICE_NAME)
    coordinator._slow_poll_pending = True
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) == "Links", (
        "a single missed answer emptied the value"
    )


async def test_a_fresh_slow_value_still_wins_over_the_cache(coordinator, fake_client):
    """Guard against the fix above pinning the cache in place."""
    await coordinator.async_refresh()  # cycle 0: slow
    fake_client.values[PATH_DEVICE_NAME] = "Renamed"

    coordinator._slow_poll_pending = True
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) == "Renamed"


async def test_a_value_confirmed_during_a_poll_is_not_overwritten(coordinator, fake_client):
    """The v1.15.1 regression test only ever covered the SEQUENTIAL order.

    It let one refresh finish, applied the confirmed value, then refreshed
    again. The order that actually bites is the other one: the poll reads the
    old value, the user changes it, the device confirms - and only then does
    the poll return and publish the snapshot it took before the change.

    The speaker is then correct while the entity shows the old value, and on a
    slow path the stale value is written back into the cache on top.
    """
    await coordinator.async_refresh()

    reached_the_slow_path = asyncio.Event()
    release = asyncio.Event()
    plain_get = fake_client.get

    async def _gated_get(path: tuple[str, ...]) -> Any:
        value = await plain_get(path)
        if path == PATH_DEVICE_NAME:
            # The poll now holds the OLD name and has not returned yet.
            reached_the_slow_path.set()
            await release.wait()
        return value

    fake_client.get = _gated_get
    coordinator._slow_poll_pending = True
    poll = asyncio.create_task(coordinator.async_refresh())

    await reached_the_slow_path.wait()
    coordinator.apply_confirmed_value(PATH_DEVICE_NAME, "Neuer Name")
    fake_client.values[PATH_DEVICE_NAME] = "Neuer Name"
    release.set()
    await poll

    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name", (
        "the finishing poll published the value it read before the change"
    )

    fake_client.get = plain_get
    await coordinator.async_refresh()
    assert _value(coordinator, PATH_DEVICE_NAME) == "Neuer Name", (
        "the stale value was written back into the slow cache"
    )


async def test_a_reread_of_a_slow_path_fetches_it_on_the_next_cycle(coordinator, fake_client):
    """An unconfirmed write must not leave the old value on screen for 5 minutes."""
    await coordinator.async_refresh()  # cycle 0: slow included
    await coordinator.async_refresh()  # cycle 1: fast only from here on
    fake_client.values[PATH_DEVICE_NAME] = "Renamed"

    coordinator.request_reread(PATH_DEVICE_NAME)
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) == "Renamed"


async def test_a_reread_requested_during_a_slow_poll_is_not_used_up_by_it(
    hass, coordinator, fake_client
):
    """The poll in flight has already read the old name when the reread comes.

    It used to clear the pending flag on its way out, so the poll asked for
    ran fast-only and merged the old name back in - for up to five minutes
    while the device already held the new one.
    """
    await coordinator.async_refresh()  # cycle 0: slow, "Links" cached
    coordinator._slow_poll_pending = True
    name_read = asyncio.Event()
    release = asyncio.Event()
    real_get = fake_client.get

    async def _get(path):
        value = await real_get(path)
        if path == PATH_DEVICE_NAME:
            name_read.set()
            await release.wait()
        return value

    fake_client.get = _get
    old_poll = hass.async_create_task(coordinator.async_refresh())
    await name_read.wait()

    fake_client.values[PATH_DEVICE_NAME] = "Renamed"
    coordinator.request_reread(PATH_DEVICE_NAME)
    release.set()
    await old_poll
    await hass.async_block_till_done()
    await coordinator.async_refresh()

    assert _value(coordinator, PATH_DEVICE_NAME) == "Renamed"


async def test_a_reread_does_not_hold_the_caller_for_a_whole_poll(hass, coordinator):
    """The caller is a failed write or a restore in the middle of its loop.

    Awaiting the refresh made the user wait for a second connect attempt
    before seeing the error, and ran a full poll - with a publish - inside the
    restore.
    """
    release = asyncio.Event()

    async def _slow_refresh() -> None:
        await release.wait()

    coordinator.async_request_refresh = _slow_refresh

    coordinator.request_reread(PATH_DEVICE_NAME)

    assert coordinator._slow_poll_pending
    release.set()
    await hass.async_block_till_done()


class _SavingClient(FakeClient):
    def __init__(self, reject: bool = False) -> None:
        super().__init__({})
        self.saved: list = []
        self.reject = reject

    async def set(self, path, value):
        if self.reject:
            raise SSCDeviceError("save rejected (test)")
        self.saved.append((path, value))
        return value


async def test_a_kh80_saves_its_settings_after_a_change(hass):
    """Only the KH 80 forgets changes at power-off unless told to save."""
    client = _SavingClient()
    coordinator = NeumannKHCoordinator(hass, client, "test", model="KH 80")

    await coordinator.async_persist()

    assert client.saved == [(("device", "save_settings"), True)]


@pytest.mark.parametrize("model", ["KH 120 II", "KH 750", None])
async def test_other_models_are_not_asked_to_save(hass, model):
    """They save by themselves, and answer the save path with a 404."""
    client = _SavingClient()
    coordinator = NeumannKHCoordinator(hass, client, "test", model=model)

    await coordinator.async_persist()

    assert client.saved == []


async def test_a_failed_save_says_the_change_will_not_survive(hass):
    from homeassistant.exceptions import HomeAssistantError

    coordinator = NeumannKHCoordinator(hass, _SavingClient(reject=True), "test", model="KH 80")

    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_persist()
    assert caught.value.translation_key == "settings_not_saved"


async def test_a_kh80_without_the_save_path_does_not_fail_every_change(hass):
    """The KH 80 need is reported, not measured. A 404 means there is nothing to save."""
    client = _SavingClient()

    async def _not_found(path, value):
        raise SSCDeviceError("address not found", code=404)

    client.set = _not_found
    coordinator = NeumannKHCoordinator(hass, client, "test", model="KH 80")

    await coordinator.async_persist()


async def test_a_save_that_times_out_is_reported_as_not_saved(hass):
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.neumann_kh.ssc_client import SSCTimeoutError

    client = _SavingClient()

    async def _timeout(path, value):
        raise SSCTimeoutError("no answer")

    client.set = _timeout
    coordinator = NeumannKHCoordinator(hass, client, "test", model="KH 80")

    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_persist()
    assert caught.value.translation_key == "settings_not_saved"


def _kh750(hass, client: FakeClient) -> NeumannKHCoordinator:
    coord = NeumannKHCoordinator(hass, client, "test", model="KH 750")
    coord.update_interval = None
    return coord


async def test_paths_only_disabled_entities_read_are_not_polled(hass):
    """On a KH 750, 9 of 21 fast paths served only entities disabled by default.

    That was about 26 000 requests a day per subwoofer nobody looked at.
    """
    client = FakeClient({})
    coord = _kh750(hass, client)
    await coord.async_refresh()  # the first refresh polls everything
    coord.async_add_listener(lambda: None, PATH_OUTPUT_MUTE)
    client.asked.clear()

    await coord.async_refresh()

    assert PATH_OUT1_LEVEL not in client.asked
    assert PATH_STANDBY_COUNTDOWN not in client.asked
    assert PATH_OUTPUT_MUTE in client.asked


async def test_an_enabled_optional_entity_gets_its_path_polled(hass):
    client = FakeClient({PATH_OUT1_LEVEL: -3.0})
    coord = _kh750(hass, client)
    coord.async_add_listener(lambda: None, PATH_OUT1_LEVEL)

    await coord.async_refresh()

    assert coord.value(PATH_OUT1_LEVEL) == -3.0


async def test_the_first_refresh_polls_every_path(hass):
    """The first refresh runs before any entity is added - none has asked yet.

    Skipping the optional paths then would leave an enabled entity unknown
    until the next cycle.
    """
    client = FakeClient({})
    coord = _kh750(hass, client)

    await coord.async_refresh()

    assert PATH_OUT1_LEVEL in client.asked


def _descriptions_with_paths(model: str):
    """Every entity description that carries an SSC path, across the platforms."""
    import importlib

    found = []
    for platform in ("sensor", "binary_sensor", "number", "select", "switch", "text"):
        module = importlib.import_module(f"custom_components.neumann_kh.{platform}")
        for value in vars(module).values():
            for item in value if isinstance(value, tuple) else (value,):
                if getattr(item, "ssc_path", None) and hasattr(item, "key"):
                    found.append(item)
    number = importlib.import_module("custom_components.neumann_kh.number")
    found.append(number._build_output_delay_description(model == "KH 750"))
    return found


@pytest.mark.parametrize("model", ["KH 120 II", "KH 750"])
def test_the_optional_poll_paths_are_exactly_those_of_disabled_entities(model):
    """A hand-kept list drifts: an entity enabled by default whose path sits
    here would stay unknown, and a new disabled one would still be polled."""
    from custom_components.neumann_kh.const import OPTIONAL_FAST_POLL_PATHS
    from custom_components.neumann_kh.coordinator import poll_paths_for_model

    fast, _ = poll_paths_for_model(model)
    descriptions = _descriptions_with_paths(model)
    enabled = {tuple(d.ssc_path) for d in descriptions if d.entity_registry_enabled_default}
    disabled = {tuple(d.ssc_path) for d in descriptions if not d.entity_registry_enabled_default}

    expected = (disabled - enabled) & {tuple(path) for path in fast}
    assert expected == OPTIONAL_FAST_POLL_PATHS & {tuple(path) for path in fast}


async def test_the_first_refresh_polls_every_path_even_with_a_listener(hass):
    """The first-refresh signal must not hang on Home Assistant internals.

    It was "no listener registered yet", read from the coordinator's private
    _listeners. A listener added before the first refresh then skipped the
    optional paths, and a rename of that attribute in Home Assistant would
    fail every cycle. "No data yet" holds exactly until the first success.
    """
    client = FakeClient({})
    coord = _kh750(hass, client)
    coord.async_add_listener(lambda: None, PATH_OUTPUT_MUTE)

    await coord.async_refresh()

    assert PATH_OUT1_LEVEL in client.asked
