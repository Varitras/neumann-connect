"""Home Assistant's reports about this integration, collected to fail the tests.

Home Assistant reports a deprecated call by logging a warning and carrying
on, so a suite stays green on code that the release named in the warning
breaks for every user at once. This catches every wording of Home
Assistant's report helpers, helpers.frame and helpers.deprecation
(test_deprecations.py produces each from Home Assistant itself), on the
paths the tests run.

Not yet: the warnings other parts of Home Assistant log themselves and end
with "please report it to the custom integration author" (an entity without
a platform, an impossible state class, a duplicate unique ID).
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import re
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "custom_components" / "neumann_kh"
# Read from the manifest, not imported: importing the integration is what
# this has to watch.
INTEGRATION = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))["domain"]
_OWN_LOGGER = f"custom_components.{INTEGRATION}"
_DOMAIN = re.escape(INTEGRATION)
# A deprecation report arrives on the logger of the deprecated object's
# module, which can be any of Home Assistant's.
_HOME_ASSISTANT_LOGGER = "homeassistant"

# The wordings of helpers.frame and helpers.deprecation (Home Assistant
# 2026.10). A call from no integration is, in this suite, the tests or what
# they drive, so it counts as well. A call from another integration does not.
# Matched at the start of the message and never across a line: a traceback
# or an argument below may quote a path or a word, and is not the report.
_REPORT = re.compile(
    "|".join(
        (
            rf"Detected that custom integration '{_DOMAIN}' ",
            r"Detected code that ",
            rf"The deprecated .+? was [^.\n]+? from {_DOMAIN}\.",
            r"The deprecated .+? was (?:(?! from )[^.\n])+\.",
        )
    )
)
# deprecated_substitute and get_deprecated name nobody; they log under the
# module that used the old name, which is ours or someone else's.
_RENAMED = re.compile(r"'[^']+' is deprecated\. Please rename ")


def _within(name: str, parent: str) -> bool:
    """Whether a logger is parent or below it; a longer name's prefix is not."""
    return name == parent or name.startswith(f"{parent}.")


def is_report(record: logging.LogRecord) -> bool:
    """Whether Home Assistant reports something this integration does."""
    if record.levelno < logging.WARNING:
        return False
    message = record.getMessage()
    if _REPORT.match(message):
        return True
    return bool(_RENAMED.match(message)) and _within(record.name, _OWN_LOGGER)


class Reports(logging.Handler):
    """The reports since the last take()."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self._pending: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        if is_report(record):
            self._pending.append(record)

    def take(self) -> list[logging.LogRecord]:
        taken, self._pending = self._pending, []
        return taken

    def check(self, when: str) -> None:
        """Fail on what arrived since the last take()."""
        reported = [record.getMessage() for record in self.take()]
        assert not reported, f"Home Assistant reported {when}: {reported[:3]}"


REPORTS = Reports()


def _reaches_the_check(logger: logging.Logger) -> bool:
    """Whether a WARNING on this logger gets to the root logger's handlers."""
    if logger.disabled or logger.getEffectiveLevel() > logging.WARNING:
        return False
    current: logging.Logger | None = logger
    while current is not None and current is not logging.root:
        if not current.propagate:
            return False
        current = current.parent
    return True


def assert_listening() -> None:
    """Fail when the check can no longer hear Home Assistant's reports.

    Asked once the test body has run: a level raised and restored within the
    body (caplog.at_level) goes unseen.
    """
    assert REPORTS in logging.root.handlers, "the deprecation check was removed"
    assert logging.root.manager.disable < logging.WARNING, (
        "logging.disable hides Home Assistant's reports from the deprecation check"
    )
    existing = [
        logging.getLogger(_HOME_ASSISTANT_LOGGER),
        logging.getLogger(_OWN_LOGGER),
        *(
            logger
            for name, logger in logging.root.manager.loggerDict.items()
            if isinstance(logger, logging.Logger)
            and (_within(name, _HOME_ASSISTANT_LOGGER) or _within(name, _OWN_LOGGER))
        ),
    ]
    deaf = sorted({logger.name for logger in existing if not _reaches_the_check(logger)})
    assert not deaf, (
        f"warnings on {deaf} no longer reach the deprecation check; "
        "pass logger= to caplog.set_level"
    )


def import_every_module() -> None:
    """Import the integration and every module in it, as Home Assistant may."""
    package = importlib.import_module(f"custom_components.{INTEGRATION}")
    for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        importlib.import_module(module.name)
