"""Tests for the export helper functions in button.py.

The filename sanitizer that used to live here is gone along with the exports
under /config/www/: no device-supplied value reaches a filesystem path any
more, so path traversal is structurally impossible rather than filtered out.
Masking stays - it keeps the serial number out of the exported content.
"""

from custom_components.neumann_kh.button import _mask_serial


def test_mask_serial_keeps_last_three():
    assert _mask_serial("ABC12345") == "xxxxx345"


def test_mask_serial_short_values_unchanged():
    assert _mask_serial("AB") == "AB"
    assert _mask_serial("ABC") == "ABC"
