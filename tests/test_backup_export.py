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
    restorable_paths_for_model,
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


# Everything the entities can write. If a platform gains a writable path and
# nobody adds it here, the test below still catches it only if the path is
# missing from the export - so keep this list in step with the platforms.
_WRITABLE = {
    "PATH_DEVICE_NAME": ("KH 120 II", "KH 750"),
    "PATH_IDENTIFY": ("KH 120 II", "KH 750"),
    "PATH_INPUT_INTERFACE_TYPE": ("KH 120 II", "KH 750"),
    "PATH_OUTPUT_DELAY": ("KH 120 II", "KH 750"),
    "PATH_OUTPUT_DIMM": ("KH 120 II", "KH 750"),
    "PATH_OUTPUT_LEVEL": ("KH 120 II", "KH 750"),
    "PATH_OUTPUT_MUTE": ("KH 120 II", "KH 750"),
    "PATH_OUTPUT_PHASE_INVERSION": ("KH 120 II", "KH 750"),
    "PATH_STANDBY_AUTO_TIME": ("KH 120 II", "KH 750"),
    "PATH_STANDBY_ENABLED": ("KH 120 II", "KH 750"),
    "PATH_STANDBY_LEVEL": ("KH 120 II", "KH 750"),
    "PATH_UI_CONTROL_MODE": ("KH 120 II", "KH 750"),
    # Model-specific: a logo only on the monitors, out1/out2 only on the sub.
    "PATH_LOGO_BRIGHTNESS": ("KH 120 II",),
    "PATH_OUT1_DELAY": ("KH 750",),
    "PATH_OUT1_LEVEL": ("KH 750",),
    "PATH_OUT1_MUTE": ("KH 750",),
    "PATH_OUT2_DELAY": ("KH 750",),
    "PATH_OUT2_LEVEL": ("KH 750",),
    "PATH_OUT2_MUTE": ("KH 750",),
}


@pytest.mark.parametrize("model", [_KH_120_II, _KH_750])
def test_every_writable_path_is_backed_up(model):
    """A backup that misses a writable value cannot restore that value.

    This is the guarantee behind "all known values": whatever an entity can
    write has to come back out of the export.
    """
    from custom_components.neumann_kh import const  # noqa: PLC0415

    covered = set(known_paths_for_model(model))
    missing = [
        name
        for name, models in _WRITABLE.items()
        if model in models and getattr(const, name) not in covered
    ]
    assert not missing, f"writable but not backed up on {model}: {missing}"


def test_no_duplicate_paths():
    # A duplicate would mean querying the device twice for the same value.
    paths = known_paths_for_model(_KH_750)
    assert len(paths) == len(set(paths))


# --- Restore allowlist ------------------------------------------------------


@pytest.mark.parametrize("model", [_KH_120_II, _KH_750])
def test_commands_are_never_restorable(model):
    """A restore must not replay commands or momentary actions.

    device/restore is the factory reset, save_settings commits to flash, and
    identification/visual makes the speaker blink. Relying on the device to
    reject them is no safeguard - these are writable, that is the point of
    them.
    """
    from custom_components.neumann_kh import const  # noqa: PLC0415

    restorable = set(restorable_paths_for_model(model))
    for name in ("PATH_RESTORE", "PATH_SAVE_SETTINGS", "PATH_IDENTIFY"):
        assert getattr(const, name) not in restorable, f"{name} must not be restorable"


@pytest.mark.parametrize("model", [_KH_120_II, _KH_750])
def test_read_only_paths_are_not_restorable(model):
    # Confirmed read-only on real hardware; writing them would only produce
    # rejections and inflate the "skipped" count.
    from custom_components.neumann_kh import const  # noqa: PLC0415

    restorable = set(restorable_paths_for_model(model))
    for name in ("PATH_INPUT_GAIN", "PATH_UI_OUTPUT_LEVEL", "PATH_WARNINGS",
                 "PATH_IDENTITY_HW_VERSION", "PATH_INPUT_CURRENT"):
        assert getattr(const, name) not in restorable, f"{name} is read-only"


@pytest.mark.parametrize("model", [_KH_120_II, _KH_750])
def test_control_mode_is_written_last(model):
    """LOCAL would cut network control - so write it after everything else."""
    from custom_components.neumann_kh import const  # noqa: PLC0415

    paths = restorable_paths_for_model(model)
    assert paths[-1] == const.PATH_UI_CONTROL_MODE


@pytest.mark.parametrize("model", [_KH_120_II, _KH_750])
def test_restorable_is_a_subset_of_the_backup(model):
    # Restoring a path that is never backed up could not work.
    assert set(restorable_paths_for_model(model)) <= set(known_paths_for_model(model))
