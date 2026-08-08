"""Tests for the small helpers behind the buttons.

Serial masking keeps the real number out of the exported content while the
store stays keyed by the real one, and the device claim decides whether a
press may start at all.
"""

import asyncio

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import HomeAssistantError

from custom_components.neumann_kh.button import _claim_device
from custom_components.neumann_kh.export_actions import mask_serial


def test_mask_serial_keeps_last_three():
    assert mask_serial("ABC12345") == "xxxxx345"


def test_mask_serial_short_values_unchanged():
    assert mask_serial("AB") == "AB"
    assert mask_serial("ABC") == "ABC"


def test_one_action_at_a_time_per_speaker():
    """Four actions used to guard themselves with three separate flags.

    Backup and discovery could therefore run at once, and the factory reset had
    no guard at all. The dangerous pair is a backup reading while a restore
    writes: the snapshot mixes values from before and after, looks complete,
    and replaces the last good one.
    """
    class _Coordinator:
        def __init__(self):
            self.action_lock = asyncio.Lock()

    async def _run():
        coordinator = _Coordinator()
        async with _claim_device(coordinator):
            # A second action while the first still owns the device.
            with pytest.raises(HomeAssistantError) as err:
                _claim_device(coordinator)
            assert err.value.translation_key == "device_action_in_progress"
        # Released again afterwards.
        assert _claim_device(coordinator) is coordinator.action_lock

    asyncio.run(_run())
