"""The "latest HA" CI job must test the newest FINAL Home Assistant.

Installing the plugin unpinned reads like "newest Home Assistant" but is not:
it ships a normal, non-prerelease version for every Home Assistant beta too,
so pip resolves to one pinning a beta. resolve_phcc.py (taken over from a
sibling project where exactly that happened) picks the newest release that
pins a final version.

Only the selection logic is exercised here - no PyPI access, so this stays a
fast unit test rather than a network-dependent one.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "resolve_phcc.py"


def _load():
    spec = importlib.util.spec_from_file_location("resolve_phcc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolve_phcc = _load()


@pytest.mark.parametrize(
    ("pin", "expected"),
    [
        ("homeassistant==2026.7.4", False),
        ("homeassistant==2026.8.0b3", True),
        ("homeassistant==2026.8.0b0", True),
        ("homeassistant==2026.8.0rc1", True),
        ("homeassistant==2026.8.0a1", True),
        # No pin at all: we cannot tell what would be installed, and the whole
        # point of the script is not having to guess.
        (None, True),
    ],
)
def test_a_prerelease_pin_is_recognised(pin, expected):
    assert resolve_phcc.is_prerelease(pin) is expected


def test_the_newest_final_release_wins_over_newer_betas():
    """The real situation at the time this was written: three plugin releases
    newer than the newest one pinning a final Home Assistant."""
    pins = {
        "0.13.351": "homeassistant==2026.8.0b3",
        "0.13.350": "homeassistant==2026.8.0b2",
        "0.13.349": "homeassistant==2026.8.0b0",
        "0.13.348": "homeassistant==2026.7.4",
        "0.13.347": "homeassistant==2026.7.3",
    }

    assert resolve_phcc.newest_stable(pins) == "0.13.348"


def test_versions_are_compared_numerically_not_as_text():
    """ "0.13.9" must not outrank "0.13.348" - which it does as a string."""
    pins = {
        "0.13.9": "homeassistant==2026.1.0",
        "0.13.348": "homeassistant==2026.7.4",
    }

    assert resolve_phcc.newest_stable(pins) == "0.13.348"


def test_nothing_usable_fails_loudly():
    """Falling back to "install whatever" would put the beta straight back."""
    with pytest.raises(SystemExit):
        resolve_phcc.newest_stable({"0.13.351": "homeassistant==2026.8.0b3"})


def test_an_explicit_requirement_is_passed_through(capsys):
    """The pinned minimum-version entry must reach pip unchanged - and must
    not trigger a PyPI lookup."""
    resolve_phcc.main(["resolve_phcc.py", "pytest-homeassistant-custom-component==0.13.190"])

    assert capsys.readouterr().out.strip() == (
        "PHCC_SPEC=pytest-homeassistant-custom-component==0.13.190"
    )
