"""The guard on the mutation run itself.

The run is only worth something if it fails loudly. A harness that skips an
entry whose target moved prints "all caught" without having checked anything -
which is the same lie as a decorative test, one level up.

Two of these run on every ordinary suite (they only read files), so plan rot
is caught long before anyone starts the slow mutation run. The ones that
spawn a pytest of their own carry the e2e marker: each costs a full plugin
start-up, and the full run is where they belong.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PLAN_PATH = REPO / ".github" / "mutations" / "plan.json"
SCRIPT = REPO / ".github" / "scripts" / "mutate.py"


def _plan() -> list[dict]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _harness():
    spec = importlib.util.spec_from_file_location("mutate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_mutation_still_matches_its_target():
    """A `find` that no longer occurs exactly once checks nothing."""
    wrong = {}
    for entry in _plan():
        source = (REPO / entry["path"]).read_text(encoding="utf-8")
        count = source.count(entry["find"])
        if count != 1:
            wrong[entry["name"]] = f"{count} matches in {entry['path']}"

    assert not wrong, (
        f"stale mutation(s): {wrong}. The code moved - update the entry, or "
        "the mutation run reports 'caught' for a breakage it never applied."
    )


def test_every_mutation_names_a_test_that_exists():
    missing = []
    for entry in _plan():
        test_file, _, test_name = entry["expect"].partition("::")
        source_path = REPO / test_file
        if not source_path.exists():
            missing.append(f"{entry['name']}: no {test_file}")
        elif f"def {test_name}(" not in source_path.read_text(encoding="utf-8"):
            missing.append(f"{entry['name']}: {test_file} has no {test_name}")

    assert not missing, f"mutation(s) pointing at a test that is gone: {missing}"


def test_the_harness_refuses_a_stale_mutation_instead_of_skipping_it():
    """Proof-of-red for the harness: a moved target must be an error."""
    harness = _harness()

    with pytest.raises(LookupError):
        harness._apply(
            {
                "name": "target that moved away",
                "path": "custom_components/neumann_kh/const.py",
                "find": "this text is not in the file",
                "replace": "",
            }
        )


@pytest.mark.e2e
@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("source", "counts_as_caught"),
    [
        ("def test_it():\n    assert False\n", True),
        (
            "import pytest\n\n@pytest.fixture\ndef f():\n    raise OSError\n\ndef test_it(f):\n    pass\n",
            False,
        ),
    ],
    # Two nested runs, not one per exit code: each costs a full plugin
    # start-up. The fixture error is the case a bare exit-code check would
    # still get wrong - pytest exits 1 for it, exactly as for a failure.
    ids=["a failing test", "a fixture error"],
)
def test_only_a_failing_test_counts_as_a_catch(source, counts_as_caught):
    """Every way a run can end non-zero, and only one of them is a catch.

    pytest exits 1 for a failed test - and also for a fixture error; 2 for a
    collection error; 4 for a node it cannot find; 5 when nothing ran. Taking
    "non-zero" as "the mutation was caught" made a plan entry whose test had
    been renamed, or whose module no longer imported, count as proof.

    The probe lives inside tests/ for the moment it runs: outside the tree
    pytest.ini does not apply, and the asyncio plugin then turns even a plain
    passing test into an error. Its name does not match test_*.py, so a run
    that starts while it exists cannot collect it by accident - only the
    explicit path here does. Each nested run pays the full plugin start-up,
    which is what the timeout above allows for.
    """
    probe = REPO / "tests" / "harness_probe.py"
    probe.write_text(source, encoding="utf-8")
    try:
        assert _harness()._run_expected_test(str(probe)) is counts_as_caught
    finally:
        probe.unlink()


@pytest.mark.e2e
@pytest.mark.timeout(120)
def test_a_test_that_does_not_exist_is_not_a_catch():
    assert _harness()._run_expected_test("tests/test_mutation_harness.py::test_nowhere") is False
