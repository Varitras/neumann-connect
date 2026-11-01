#!/usr/bin/env python3
"""Import every module of the integration; fail if Home Assistant reports one.

The test suite checks the same, but it needs
pytest-homeassistant-custom-component, which pins one Home Assistant release
and follows a beta days later, if at all. This needs Home Assistant alone, so
the look at the next release runs it on the beta itself
(.github/workflows/ha-next.yml).

    python .github/scripts/import_check.py
"""

from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "tests")]

from deprecations import INTEGRATION, REPORTS, import_every_module


def main() -> int:
    """Exit 1 when Home Assistant reported anything while importing."""
    logging.getLogger().addHandler(REPORTS)
    for category in (DeprecationWarning, PendingDeprecationWarning):
        warnings.filterwarnings(
            "error", category=category, module=rf"custom_components\.{INTEGRATION}"
        )
    import_every_module()
    reported = [record.getMessage() for record in REPORTS.take()]
    for message in reported:
        print(message, file=sys.stderr)
    return 1 if reported else 0


if __name__ == "__main__":
    sys.exit(main())
