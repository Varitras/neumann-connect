"""No log line hands out a serial number in full.

Home Assistant logs are a routine support attachment, and a serial identifies
one specific speaker. The exported files have run through `mask_serial()`
since 1.17; the zeroconf mismatch warning still printed both the announced
and the answered serial verbatim:

    _LOGGER.warning(
        "Ignoring an announcement for %s: %s answered with serial %s",
        serial, host, identity.serial,
    )

A behavioural test for this would have to drive the whole discovery step; a
scan over the package sees every log call at once, including the ones written
next week.
"""

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"

MASK = "mask_serial"
SENSITIVE = "serial"


def _is_masked(node) -> bool:
    """A call to mask_serial(...) anywhere inside the argument."""
    return any(
        isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == MASK
        for inner in ast.walk(node)
    )


def _mentions_a_serial(node) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and SENSITIVE in inner.id.lower():
            return True
        if isinstance(inner, ast.Attribute) and SENSITIVE in inner.attr.lower():
            return True
    return False


def _unmasked_log_arguments(source: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        is_logger_call = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id.endswith("LOGGER")
        )
        if not is_logger_call:
            continue
        for argument in node.args[1:]:
            if _mentions_a_serial(argument) and not _is_masked(argument):
                yield node.lineno, ast.unparse(argument)


def test_no_log_call_passes_an_unmasked_serial():
    offenders = [
        f"{source_file.name}:{line}: {argument}"
        for source_file in sorted(PACKAGE.glob("*.py"))
        for line, argument in _unmasked_log_arguments(source_file.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        "log call(s) passing a serial in full:\n  "
        + "\n  ".join(offenders)
        + f"\nWrap it in {MASK}() - the tail stays readable, the device stops "
        "being identifiable from a shared log."
    )


def test_the_scan_catches_the_line_it_was_written_for():
    """Proof-of-red, with the verbatim shape from the incident."""
    incident = """
_LOGGER.warning(
    "Ignoring an announcement for %s: %s answered with serial %s",
    serial,
    host,
    identity.serial,
)
"""
    fixed = """
_LOGGER.warning(
    "Ignoring an announcement for %s: %s answered with serial %s",
    mask_serial(serial),
    host,
    mask_serial(identity.serial),
)
"""

    assert list(_unmasked_log_arguments(incident)), "the incident line must be flagged"
    assert not list(_unmasked_log_arguments(fixed)), "the masked form must pass"
