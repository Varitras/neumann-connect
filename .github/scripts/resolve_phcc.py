"""Pick the pytest-homeassistant-custom-component release to test against.

The test matrix wants "the newest Home Assistant our users can actually be
running". Installing the plugin unpinned does NOT give that: the plugin
publishes a normal, non-prerelease version for every Home Assistant BETA as
well, so `pip install pytest-homeassistant-custom-component` resolves to a
release pinning e.g. homeassistant==2026.8.0b3. pip's own prerelease
exclusion cannot see that - the plugin version is stable, only what it
depends on is not.

The effect is quiet and bad: the job named "current HA" stops covering the
release people run, and a regression against current stable ships green.

So the newest release whose Home Assistant pin is a final version is chosen
explicitly. A literal requirement (the pinned minimum-version entry of the
matrix) is passed through untouched.

Usage:
    python resolve_phcc.py latest-stable-ha  ->  PHCC_SPEC=...==0.13.348
    python resolve_phcc.py 'pkg==0.13.190'   ->  PHCC_SPEC=pkg==0.13.190
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

PACKAGE = "pytest-homeassistant-custom-component"
SENTINEL = "latest-stable-ha"

# 2026.8.0b3 / 2026.8.0rc1 - anything that is not a plain X.Y.Z release.
_PRERELEASE = re.compile(r"\d+(?:a|b|rc)\d*$")


def is_prerelease(pin: str | None) -> bool:
    """Whether a `homeassistant==...` requirement names a prerelease."""
    if not pin:
        # No pin at all means we cannot tell what will be installed, which is
        # exactly the uncertainty this script exists to remove.
        return True
    return bool(_PRERELEASE.search(pin.strip()))


def home_assistant_pin(requires_dist) -> str | None:
    for requirement in requires_dist or []:
        if requirement.lower().startswith("homeassistant"):
            return requirement
    return None


def sort_key(version: str):
    return [int(part) for part in re.findall(r"\d+", version)]


def newest_stable(pins: dict[str, str | None]) -> str:
    """Return the highest version in `pins` whose Home Assistant is final."""
    for version in sorted(pins, key=sort_key, reverse=True):
        if not is_prerelease(pins[version]):
            return version
    raise SystemExit(
        "No pytest-homeassistant-custom-component release pins a final Home "
        "Assistant version. Refusing to guess - fix the matrix by hand."
    )


# One network blip on PyPI's side turned a tag build red on 2026-09-10, while
# the same commit had passed seconds earlier. A few tries absorb that; after
# the last one the error goes through and the run stops - this script never
# falls back to a version it could not look up.
FETCH_ATTEMPTS = 3
FETCH_RETRY_SECONDS = 5


def _worth_another_try(error: OSError) -> bool:
    """Whether the failure says something about the network, not the request.

    HTTPError is a URLError, so it has to be told apart first: a 404 is PyPI
    answering that the thing does not exist, and asking again only hides that
    the matrix names something wrong. A 5xx is the server having a moment.
    """
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    return True


def _read(url: str):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def _fetch(url: str):
    for _ in range(FETCH_ATTEMPTS - 1):
        try:
            return _read(url)
        except OSError as error:
            if not _worth_another_try(error):
                raise
            print(
                f"PyPI did not answer ({error}); trying again in {FETCH_RETRY_SECONDS} s.",
                file=sys.stderr,
            )
            time.sleep(FETCH_RETRY_SECONDS)
    return _read(url)


def recent_pins(candidates: int = 20) -> dict[str, str | None]:
    """The newest plugin releases on PyPI and the Home Assistant each pins.

    Separate from the choice below because two callers want the table: the
    matrix wants the newest stable release, and check_current_ha.py wants to
    know which Home Assistant that release ships.
    """
    index = _fetch(f"https://pypi.org/pypi/{PACKAGE}/json")
    published = [version for version, files in index["releases"].items() if files]
    recent = sorted(published, key=sort_key, reverse=True)[:candidates]
    return {
        version: home_assistant_pin(
            _fetch(f"https://pypi.org/pypi/{PACKAGE}/{version}/json")["info"].get("requires_dist")
        )
        for version in recent
    }


def resolve_from_pypi(candidates: int = 20) -> str:
    return newest_stable(recent_pins(candidates))


def main(argv: list[str]) -> int:
    requested = argv[1] if len(argv) > 1 else SENTINEL
    if requested != SENTINEL:
        spec = requested
    else:
        spec = f"{PACKAGE}=={resolve_from_pypi()}"
    # Printed as an environment assignment so the workflow can append it to
    # $GITHUB_ENV in one step. Also echoed to the log, since "which Home
    # Assistant did this run actually test?" is the first question when a
    # matrix job disagrees with a local run.
    print(f"PHCC_SPEC={spec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
