"""Tests for the serial masking used in exports.

Masking keeps the real serial number out of the exported content; the store
is still keyed by the real one for mapping and retrieval.
"""

from custom_components.neumann_kh.export_actions import mask_serial


def test_mask_serial_keeps_last_three():
    assert mask_serial("ABC12345") == "xxxxx345"


def test_mask_serial_short_values_unchanged():
    assert mask_serial("AB") == "AB"
    assert mask_serial("ABC") == "ABC"
