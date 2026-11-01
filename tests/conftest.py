"""Shared test configuration.

Makes the repo root importable (`custom_components.neumann_kh...`)
regardless of the directory pytest is started from, and fails a test during
which Home Assistant reported this integration (see deprecations.py).

The suite targets Linux (WSL2 or CI) and does not run on native Windows:
pytest-homeassistant-custom-component imports `homeassistant.runner` at
collection time, which imports the Unix-only `fcntl` module.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Generator, Iterator

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deprecations import REPORTS, assert_listening, import_every_module

# Before any test module imports the integration: a deprecated constant is
# reported the moment a module imports it, while pytest collects.
logging.getLogger().addHandler(REPORTS)


@pytest.fixture(autouse=True)
def no_deprecation_reported() -> Iterator[None]:
    """Fail a test during which Home Assistant reported the integration.

    What arrived before it fails it too: a deprecated constant reports while
    the tests are collected, and the first test of a run is where that can
    still fail something. Autouse, so it is set up before and torn down after
    the hass fixture - Home Assistant reports while stopping as well.
    """
    REPORTS.check("before this test, outside any test")
    yield
    REPORTS.check("during this test")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call() -> Generator[None, object, object]:
    """Fail a test that stopped the deprecation check hearing reports.

    Checked right after the test body, while its fixtures still hold:
    caplog puts the levels back at its own teardown.
    """
    result = yield
    assert_listening()
    return result


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the run on what no test was there to see.

    Reports after the last test's own check, such as from a session fixture
    torn down with it, and deprecated constants in modules the selected tests
    never imported, or that do not import at all. A run that already failed
    is only told: its exit status says more about what went wrong, and
    nothing is imported over a collection error.
    """
    would_pass = session.exitstatus in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED)
    problems = []
    if would_pass:
        try:
            import_every_module()
        except Exception as error:  # noqa: BLE001 - any import failure fails the run
            problems.append(f"importing the integration failed: {error!r}")
    problems += [record.getMessage() for record in REPORTS.take()]
    for problem in problems:
        sys.stderr.write(f"Home Assistant reported after the last test: {problem}\n")
    if problems and would_pass:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
