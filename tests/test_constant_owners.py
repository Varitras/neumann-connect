"""Every constant has exactly one owning module.

The rule (CLAUDE.md): a value needed across module boundaries is defined once
in the module that owns the term and imported from there. A second
hand-written definition is the bug of tomorrow - whoever turns one dial
leaves the other standing.

Found by audit, not by any analyser: `_MAX_PARALLEL_IDENTITY_QUERIES = 8`
lived in both `__init__.py` and `config_flow.py`, and the comment on one of
them said "Mirrors the config flow". Neither SonarCloud nor DeepSource
reports it, because each file is correct on its own.
"""

import ast
import pathlib
from collections import defaultdict

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"

# A name may repeat where it is a per-module fact rather than a shared value.
EXEMPT = {
    # The Home Assistant idiom: every module logs under its own __name__.
    # A single shared logger would attribute every message to one module.
    "_LOGGER",
}


def _module_level_constants(source: str) -> set:
    """Names assigned at module level in SCREAMING_CASE, plus private ones."""
    tree = ast.parse(source)
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            bare = target.id.lstrip("_")
            if bare.isupper() and len(bare) > 1:
                found.add(target.id)
    return found


def _owners() -> dict:
    by_name = defaultdict(set)
    for source_file in sorted(PACKAGE.glob("*.py")):
        for name in _module_level_constants(source_file.read_text(encoding="utf-8")):
            by_name[name].add(source_file.name)
    return by_name


def test_no_constant_is_defined_in_two_modules():
    duplicated = {
        name: sorted(modules)
        for name, modules in _owners().items()
        if len(modules) > 1 and name not in EXEMPT
    }

    assert not duplicated, (
        f"constant(s) defined more than once: {duplicated}. Define the value "
        "once in the module that owns the term and import it - two "
        "hand-written copies drift the first time one of them is tuned."
    )


def test_the_scan_sees_a_duplicate_it_is_given():
    """Proof-of-red, with the shape from the incident."""
    first = _module_level_constants("_MAX_PARALLEL_IDENTITY_QUERIES = 8\n")
    second = _module_level_constants("_MAX_PARALLEL_IDENTITY_QUERIES = 8\nOTHER = 1\n")

    assert "_MAX_PARALLEL_IDENTITY_QUERIES" in first & second
    assert "notAConstant" not in _module_level_constants("notAConstant = 8\n")
