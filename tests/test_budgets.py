"""Size and complexity may only ever go down (the anti-erosion ratchet).

Two rules, because the two numbers behave differently:

  Lines are a CEILING. They move on almost every change, so a module simply
  may not grow past its entry. Modules under LINE_LIMIT need no entry.

  Complexity is a RATCHET - an exact match. It changes rarely, and when a
  function gets simpler that progress is locked in rather than left as
  headroom for the next person to spend.

Raising an entry is allowed as a deliberate, visible act with a reason next
to the number. Visibility alone is not enough - one project in this family
raised 26 of 37 ceilings and lowered none - so audits check the raises as
their own question.

Frozen 2026-09-01 at the numbers of v1.18.1b4.
"""

import ast
import pathlib

import complexity

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"

# The gap in this package runs between 444 (ssc_client.py) and 785
# (config_flow.py); the limit sits in it, so only the module carrying real
# history needs an entry.
LINE_LIMIT = 500
LINE_BUDGETS = {
    # Four flows (manual, zeroconf, scan, reconfigure) plus their shared
    # identity handling. Splitting was considered and rejected: the flows
    # share the candidate/identity helpers, and HA discovers the class here.
    "config_flow.py": 785,
}

# SonarSource's default. Everything above needs a written entry.
COMPLEXITY_LIMIT = 15
COMPLEXITY_BUDGETS = {
    # The one function this project keeps having trouble with. Documented as
    # an open decision (ledger E1) rather than split under time pressure:
    # every previous attempt moved the branching instead of removing it.
    "ssc_client.py::SSCClient._read_lines_until_settled": 35,
    # Writes, counts and reports per path, with a deadline between paths and
    # two ways out that both have to keep what already landed.
    "export_actions.py::async_run_restore": 20,
    # Walks an unknown schema one level at a time against two budgets.
    "discovery_export.py::_async_discover_via_schema": 18,
    # Matches an announcement against known entries, unknown devices and
    # devices that answer with a different serial than announced.
    "config_flow.py::NeumannKHConfigFlow.async_step_zeroconf": 17,
}


def _line_counts() -> dict[str, int]:
    return {
        source_file.name: len(source_file.read_text(encoding="utf-8").splitlines())
        for source_file in sorted(PACKAGE.glob("*.py"))
    }


def _scores() -> dict[str, int]:
    found = {}
    for source_file in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for name, node in complexity.functions(tree):
            found[f"{source_file.name}::{name}"] = complexity.score(node)
    return found


def test_no_module_grows_past_its_budget():
    too_big = {
        name: count
        for name, count in _line_counts().items()
        if count > LINE_BUDGETS.get(name, LINE_LIMIT)
    }

    assert not too_big, (
        f"module(s) over budget: {too_big}. Split the module, or - if the "
        "growth is warranted - raise its entry in LINE_BUDGETS in the same "
        "commit, with a one-line reason."
    )


def test_a_shrunk_module_is_not_left_with_its_old_budget():
    counts = _line_counts()
    stale = {
        name: (budget, counts.get(name, 0))
        for name, budget in LINE_BUDGETS.items()
        if counts.get(name, 0) < budget * 0.9
    }

    assert not stale, (
        f"budget far above real size: {stale} (budget, current). Lower the "
        "entry to today's count - shrinkage is progress worth locking in."
    )


def test_no_function_is_more_complex_than_its_budget():
    scores = _scores()
    over = {
        name: score
        for name, score in scores.items()
        if score > COMPLEXITY_BUDGETS.get(name, COMPLEXITY_LIMIT)
    }

    assert not over, (
        f"function(s) over budget: {over}. Cognitive complexity counts "
        "NESTING, so a guard clause or an early return usually helps more "
        "than extracting a helper."
    )


def test_every_complexity_budget_matches_exactly():
    """The ratchet half: a function that got simpler writes that down."""
    scores = _scores()
    out_of_step = {
        name: (budget, scores.get(name))
        for name, budget in COMPLEXITY_BUDGETS.items()
        if scores.get(name) != budget
    }

    assert not out_of_step, (
        f"budget out of step: {out_of_step} (budget, actual). A function got "
        "simpler, was renamed or is gone - set the entry to the current value "
        "or drop it. Headroom left lying around gets spent."
    )
