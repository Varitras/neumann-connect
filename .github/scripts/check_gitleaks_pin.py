#!/usr/bin/env python3
"""Fail unless the gitleaks release the secret-scan job pins is the latest.

Dependabot follows `uses:` lines only. A release pinned in a `run:` step is
invisible to it, so the pin would age until somebody remembered - and drift
findings are exactly what "somebody will remember" produces. So check.sh asks
GitHub for the latest release instead and fails while the pin is behind,
printing the version and the asset digest the workflow needs, so the bump is
one edit. Needs the network; a check that cannot ask is a failure, not a pass.
"""

import json
import pathlib
import re
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
# The page, not the API: GitHub limits unauthenticated API requests per address,
# CI runners share addresses, and a current pin once failed on that limit.
LATEST_RELEASE = "https://github.com/gitleaks/gitleaks/releases/latest"
LATEST_RELEASE_DETAILS = "https://api.github.com/repos/gitleaks/gitleaks/releases/latest"
ASSET_NAME = "gitleaks_{version}_linux_x64.tar.gz"


def pinned_version(workflow_text: str) -> str:
    """The GITLEAKS_VERSION the workflow installs; a workflow without one is
    not a pin to check but a scan whose version nobody chose."""
    match = re.search(r'GITLEAKS_VERSION:\s*"([\d.]+)"', workflow_text)
    if match is None:
        raise SystemExit("the secret-scan job pins no GITLEAKS_VERSION")
    return match.group(1)


def latest_version() -> str:
    """The newest gitleaks version: the release the latest page redirects to."""
    with urllib.request.urlopen(LATEST_RELEASE, timeout=30) as response:
        address = response.url
    match = re.search(r"/releases/tag/v(\d+(?:\.\d+)+)$", address)
    if match is None:
        raise OSError(f"{LATEST_RELEASE} led to {address}, which names no release")
    return match.group(1)


def published_digest(version: str) -> str | None:
    """The digest of the Linux asset, or None while the API does not answer."""
    try:
        with urllib.request.urlopen(LATEST_RELEASE_DETAILS, timeout=30) as response:
            release = json.load(response)
    except OSError:
        return None
    wanted = ASSET_NAME.format(version=version)
    digest = next(
        (asset.get("digest") for asset in release.get("assets", []) if asset.get("name") == wanted),
        None,
    )
    return (digest or "").removeprefix("sha256:") or None


def main() -> int:
    pinned = pinned_version(WORKFLOW.read_text(encoding="utf-8"))
    try:
        latest = latest_version()
    except OSError as exc:
        print(
            f"could not ask GitHub for the latest gitleaks release ({exc}). A pin "
            "that cannot be compared is not known to be current - retry with the "
            "network available.",
            file=sys.stderr,
        )
        return 1
    if pinned != latest:
        digest = published_digest(latest)
        print(
            f"the secret-scan job pins gitleaks {pinned}; the latest release "
            f"is {latest}. In .github/workflows/ci.yml set GITLEAKS_VERSION "
            f'to "{latest}" and GITLEAKS_SHA256 to '
            f'"{digest or "<the digest GitHub shows for the linux_x64 asset>"}".',
            file=sys.stderr,
        )
        return 1
    print(f"secret-scan job pins gitleaks {pinned}, the latest release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
