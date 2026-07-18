"""Tests for the path set a backup or discovery covers.

The README promises "all known values except live measurements". Earlier
versions exported only the fast poll paths, silently dropping the slow ones
(rear-panel switches, device name) and the entire EQ.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh.backup_export import (  # noqa: E402
    known_paths_for_model,
)
from custom_components.neumann_kh.const import (  # noqa: E402
    PATH_LOGO_BRIGHTNESS,
    POLL_PATHS,
    SLOW_POLL_PATHS,
    SUBWOOFER_POLL_PATHS,
    SUBWOOFER_SLOW_POLL_PATHS,
)

_KH_120_II = "KH 120 II"
_KH_750 = "KH 750"


def test_fast_and_slow_paths_are_both_covered():
    paths = set(known_paths_for_model(_KH_120_II))
    assert set(POLL_PATHS) <= paths
    # The regression: these were missing entirely.
    assert set(SLOW_POLL_PATHS) <= paths


def test_eq_is_covered_with_every_leaf():
    paths = set(known_paths_for_model(_KH_120_II))
    # Verified against a KH 120 II: a container exposes these six leaves.
    for leaf in ("enabled", "gain", "boost", "frequency", "q", "type"):
        assert ("audio", "out", "eq2", leaf) in paths


def test_subwoofer_paths_only_for_the_subwoofer_model():
    kh120 = set(known_paths_for_model(_KH_120_II))
    kh750 = set(known_paths_for_model(_KH_750))

    assert set(SUBWOOFER_POLL_PATHS) <= kh750
    assert set(SUBWOOFER_SLOW_POLL_PATHS) <= kh750
    assert not set(SUBWOOFER_POLL_PATHS) & kh120

    # The KH 750 drives two outputs, so it carries EQ containers the KH 120 II
    # does not have.
    assert ("audio", "out1", "eq2", "gain") in kh750
    assert ("audio", "out1", "eq2", "gain") not in kh120


def test_model_specific_extras_are_covered():
    # The coordinator adds the logo brightness for these models; the export
    # used to leave it out, so a backup silently lacked it.
    assert PATH_LOGO_BRIGHTNESS in known_paths_for_model(_KH_120_II)
    # The KH 750 has no logo, so it must not be queried there.
    assert PATH_LOGO_BRIGHTNESS not in known_paths_for_model(_KH_750)


def test_no_duplicate_paths():
    # A duplicate would mean querying the device twice for the same value.
    paths = known_paths_for_model(_KH_750)
    assert len(paths) == len(set(paths))
