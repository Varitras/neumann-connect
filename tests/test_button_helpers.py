"""Tests für die Export-Hilfsfunktionen in button.py (Maskierung, Sanitize)."""

from custom_components.neumann_kh.button import _mask_serial, _sanitize_filename_part


def test_mask_serial_keeps_last_three():
    assert _mask_serial("ABC12345") == "xxxxx345"


def test_mask_serial_short_values_unchanged():
    assert _mask_serial("AB") == "AB"
    assert _mask_serial("ABC") == "ABC"


def test_sanitize_removes_path_traversal():
    result = _sanitize_filename_part("../../etc/passwd")
    assert "/" not in result
    assert ".." not in result


def test_sanitize_keeps_safe_chars():
    assert _sanitize_filename_part("ABC123-x_9") == "ABC123-x_9"


def test_sanitize_empty_fallback():
    assert _sanitize_filename_part("") == "unbekannt"


def test_sanitize_masked_serial_stays_safe():
    # Kombination wie im Backup-Button: erst maskieren, dann bereinigen.
    evil = "..%2F..%2Fetc"
    safe = _sanitize_filename_part(_mask_serial(evil))
    assert all(c.isalnum() or c in "_-" for c in safe)
