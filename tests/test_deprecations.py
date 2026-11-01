"""Guard: Home Assistant's reports about this integration fail the suite.

Home Assistant reports a deprecated call by logging a warning and carrying on,
so a suite stays green until the release named in the warning breaks it for
every user at once. The probes below produce each wording from Home Assistant
itself, so a rewording turns this file red instead of the check going blind.
"""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

import conftest
from deprecations import INTEGRATION, REPORTS, assert_listening, import_every_module
from homeassistant.core import HomeAssistant
from homeassistant.helpers.deprecation import (
    deprecated_function,
    deprecated_hass_argument,
    deprecated_substitute,
    get_deprecated,
)
from homeassistant.helpers.frame import ReportBehavior, report_usage

# Where Home Assistant looks for the integration behind a call: the frame of a
# file under custom_components/<domain>/. The module's own file name, as
# get_deprecated finds the caller's module by it.
SENSOR_MODULE = f"custom_components.{INTEGRATION}.sensor"
CALLER_FILE = str(importlib.import_module(SENSOR_MODULE).__file__)
# Code outside every integration, as a test helper is: Home Assistant then
# reports without naming anyone.
ELSEWHERE_FILE = str(Path(__file__).parent / "helper.py")
OTHER_INTEGRATION_FILE = "/config/custom_components/other/sensor.py"
CORE_INTEGRATION_FILE = "/usr/lib/homeassistant/components/demo/light.py"

RENAMED_PROPERTY = """
class Entity:
    old_name = 1

    @deprecated_substitute("old_name")
    def new_name(self):
        return 2

Entity().new_name()
"""


def _call_from(file_name: str, source: str, **names: object) -> None:
    """Run source as if it were a line of that file."""
    code = compile(source, file_name, "exec")
    exec(code, names)  # noqa: S102 - the frame Home Assistant attributes reports by


def _helpers(hass: HomeAssistant) -> dict[str, object]:
    return {
        "replaced": deprecated_function("its replacement")(lambda: None),
        "takes_no_hass": deprecated_hass_argument()(lambda: None),
        "report_usage": report_usage,
        "get_deprecated": get_deprecated,
        "deprecated_substitute": deprecated_substitute,
        "LOG": ReportBehavior.LOG,
        "hass": hass,
    }


# Every wording Home Assistant's report helpers use, each from the place that
# makes it ours. Each probe is caught by one rule only: a probe two rules catch
# leaves one of them untested.
REPORT_PROBES = {
    "misuse, from the integration": (
        CALLER_FILE,
        "report_usage('calls something that goes away')",
        "Detected that custom integration",
    ),
    "misuse, from no integration": (
        ELSEWHERE_FILE,
        "report_usage('calls something that goes away', core_behavior=LOG)",
        "Detected code that",
    ),
    "deprecated function, from the integration": (
        CALLER_FILE,
        "replaced()",
        "The deprecated function",
    ),
    "deprecated function, from no integration": (
        ELSEWHERE_FILE,
        "replaced()",
        "The deprecated function",
    ),
    "hass argument, from no integration": (
        ELSEWHERE_FILE,
        "takes_no_hass(hass)",
        "The deprecated argument hass was passed to",
    ),
    "renamed configuration key, read by the integration": (
        CALLER_FILE,
        "get_deprecated({'old': 1}, 'new', 'old')",
        "'old' is deprecated",
    ),
    "renamed property, on an integration class": (
        CALLER_FILE,
        RENAMED_PROPERTY,
        "'old_name' is deprecated",
    ),
}


@pytest.mark.parametrize("probe", REPORT_PROBES)
async def test_the_deprecation_check_recognises_home_assistants_reports(
    hass: HomeAssistant, probe: str
) -> None:
    """Produced by Home Assistant itself: a rewording fails here, not silently."""
    file_name, source, opening = REPORT_PROBES[probe]
    names = {"__name__": SENSOR_MODULE} if file_name == CALLER_FILE else {}
    _call_from(file_name, source, **names, **_helpers(hass))

    reported = [record.getMessage() for record in REPORTS.take()]
    assert len(reported) == 1, reported
    assert reported[0].startswith(opening), reported


def _logs_with_a_traceback() -> None:
    try:
        raise ValueError(f"custom_components/{INTEGRATION}/deprecation-test/ssc_client.py")
    except ValueError:
        logging.getLogger(f"custom_components.{INTEGRATION}.ssc_client").warning(
            "Write failed", exc_info=True
        )


NOT_OURS: dict[str, Callable[[HomeAssistant], None]] = {
    "misuse, from another integration": lambda hass: _call_from(
        OTHER_INTEGRATION_FILE, "report_usage('does x')", **_helpers(hass)
    ),
    "deprecated function, from a core integration": lambda hass: _call_from(
        CORE_INTEGRATION_FILE, "replaced()", **_helpers(hass)
    ),
    "renamed configuration key, read elsewhere": lambda hass: _call_from(
        ELSEWHERE_FILE, "get_deprecated({'old': 1}, 'new', 'old')", **_helpers(hass)
    ),
    "own warning quoting the word": lambda _hass: logging.getLogger(
        f"custom_components.{INTEGRATION}.coordinator"
    ).warning("The speaker calls %s deprecated", "this mode"),
    "own warning with a traceback through a path named so": (
        lambda _hass: _logs_with_a_traceback()
    ),
    "renamed configuration key, from a longer logger name": lambda _hass: logging.getLogger(
        f"custom_components.{INTEGRATION}_dev.sensor"
    ).warning("'old' is deprecated. Please rename 'old' to 'new' in your configuration file."),
    "own warning naming the integration on a later line": lambda _hass: logging.getLogger(
        f"custom_components.{INTEGRATION}"
    ).warning("Speaker unavailable\nThe deprecated x was used from %s.", INTEGRATION),
}


@pytest.mark.parametrize("case", NOT_OURS)
async def test_the_deprecation_check_lets_other_reports_pass(
    hass: HomeAssistant, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Counter-check: each case logs a warning, and none of them is ours."""
    NOT_OURS[case](hass)

    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert REPORTS.take() == []


def _a_report(when: str = "does a thing") -> None:
    logging.getLogger("homeassistant.helpers.frame").warning(
        "Detected that custom integration '%s' %s", INTEGRATION, when
    )


def test_a_report_during_a_test_fails_it() -> None:
    _a_report()
    with pytest.raises(AssertionError, match="does a thing"):
        REPORTS.check("during this test")
    REPORTS.check("after the take")


# Deprecation reports arrive on the deprecated object's module: any of Home
# Assistant's loggers, not only the few the helpers name.
UNLISTED = "homeassistant.helpers.device_registry"


@contextmanager
def _restoring_logging() -> Iterator[None]:
    """Undo what a case does to logging before the test body ends."""
    root = logging.getLogger()
    touched = [
        logging.getLogger(name)
        for name in (f"custom_components.{INTEGRATION}", "homeassistant", UNLISTED)
    ]
    saved = [(logger.level, logger.propagate, logger.disabled) for logger in touched]
    root_level = root.level
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)
        root.setLevel(root_level)
        for logger, (level, propagate, disabled) in zip(touched, saved, strict=True):
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled
        if REPORTS not in root.handlers:
            root.addHandler(REPORTS)


SILENCERS: dict[str, Callable[[], None]] = {
    "root level raised": lambda: logging.getLogger().setLevel(logging.ERROR),
    "own logger raised": lambda: logging.getLogger(f"custom_components.{INTEGRATION}").setLevel(
        logging.ERROR
    ),
    "logging disabled": lambda: logging.disable(logging.WARNING),
    "Home Assistant's loggers cut off": lambda: setattr(
        logging.getLogger("homeassistant"), "propagate", False
    ),
    "check removed": lambda: logging.getLogger().removeHandler(REPORTS),
    "a Home Assistant logger raised": lambda: logging.getLogger(UNLISTED).setLevel(logging.ERROR),
    "a Home Assistant logger disabled": lambda: setattr(
        logging.getLogger(UNLISTED), "disabled", True
    ),
}


@pytest.mark.parametrize("silencer", SILENCERS)
def test_the_check_notices_when_it_cannot_hear(silencer: str) -> None:
    """What the runtest hook asks after every test body - hence restored inside it."""
    assert_listening()
    with _restoring_logging():
        SILENCERS[silencer]()
        with pytest.raises(AssertionError):
            assert_listening()


INNER_TESTS = """
import logging

import pytest


def _report(when):
    logging.getLogger("homeassistant.helpers.frame").warning(
        "Detected that custom integration '{domain}' reports %s", when
    )


_report("at collection")


@pytest.fixture(scope="session")
def reports_on_the_way_out():
    yield
    _report("after the last test")


def test_first():
    pass


def test_reports(reports_on_the_way_out):
    _report("during a test")


def test_hides_the_logs(caplog):
    caplog.set_level(logging.ERROR)
"""


@pytest.mark.e2e
@pytest.mark.timeout(240)
def test_the_suite_fails_on_reports_where_they_happen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real conftest.py in a pytest run of its own.

    A report at collection, during a test and after the last one, and a test
    that stops the check hearing, each end up as a failure.
    """
    (tmp_path / "test_inner.py").write_text(
        INNER_TESTS.format(domain=INTEGRATION), encoding="utf-8"
    )
    tests_dir = Path(__file__).parent
    result = subprocess.run(  # noqa: S603 - the interpreter running this suite
        [
            sys.executable,
            *("-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider"),
            *("-o", "asyncio_mode=auto"),
            *("-o", "asyncio_default_fixture_loop_scope=function"),
            "test_inner.py",
        ],
        cwd=tmp_path,
        env={
            # The outer run's options are not the inner run's: --maxfail=1
            # would stop it at the first of the failures it has to show.
            **{name: value for name, value in os.environ.items() if not name.startswith("PYTEST_")},
            "PYTHONPATH": os.pathsep.join((str(tests_dir), str(tests_dir.parent))),
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == pytest.ExitCode.TESTS_FAILED, output
    for expected in (
        "reported before this test, outside any test",
        "reports at collection",
        "reported during this test",
        "reports during a test",
        "no longer reach the deprecation check",
        "reported after the last test",
        "reports after the last test",
    ):
        assert expected in output, output


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED),
        (pytest.ExitCode.NO_TESTS_COLLECTED, pytest.ExitCode.TESTS_FAILED),
        (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERRUPTED),
        (pytest.ExitCode.USAGE_ERROR, pytest.ExitCode.USAGE_ERROR),
    ],
)
def test_a_report_after_the_last_test_keeps_a_more_telling_exit_status(
    before: pytest.ExitCode, after: pytest.ExitCode
) -> None:
    """A run that already failed keeps the status that says why."""
    _a_report()
    session = SimpleNamespace(exitstatus=before)
    conftest.pytest_sessionfinish(session)
    REPORTS.take()
    assert session.exitstatus == after


def _breaks_on_import() -> None:
    raise SyntaxError("invalid syntax (sensor.py, line 1)")


def test_a_module_that_does_not_import_fails_a_passing_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(conftest, "import_every_module", _breaks_on_import)
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    conftest.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert "sensor.py" in capsys.readouterr().err


def test_a_failed_run_is_left_as_it_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A collection error stays exit 2: nothing is imported over it."""
    imported: list[bool] = []
    monkeypatch.setattr(conftest, "import_every_module", lambda: imported.append(True))
    session = SimpleNamespace(exitstatus=pytest.ExitCode.INTERRUPTED)
    conftest.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.INTERRUPTED
    assert imported == []


def test_the_end_of_a_run_imports_what_no_selected_test_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial run still sees a deprecated constant in any module."""
    monkeypatch.setattr(conftest, "import_every_module", _a_report)
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    conftest.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_importing_the_integration_reports_no_deprecation() -> None:
    """A deprecated constant reports when a module imports it."""
    import_every_module()
    REPORTS.check("while importing the integration")


@pytest.mark.parametrize("category", [DeprecationWarning, PendingDeprecationWarning])
def test_a_deprecation_warning_in_the_integration_fails(category: type[Warning]) -> None:
    """pytest.ini turns them into errors, for this package only."""
    with pytest.raises(category):
        warnings.warn_explicit(
            "old", category, CALLER_FILE, 1, module=f"custom_components.{INTEGRATION}.x"
        )
    with warnings.catch_warnings(record=True) as elsewhere:
        warnings.simplefilter("always")
        warnings.warn_explicit("old", category, "other.py", 1, module="other")
    assert len(elsewhere) == 1
