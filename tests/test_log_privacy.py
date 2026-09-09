"""No log line hands out a device identifier in full.

Home Assistant logs are a routine support attachment. A serial identifies one
specific speaker; so does a link-local address, which is built from the MAC -
fe80::0a1b:2cff:fe3d:4e5f carries 08:1b:2c:3d:4e:5f.

Two rules, because the two identifiers are not equally sensitive:

* A serial is masked everywhere, including `debug`.
* A host is masked from `info` upwards. `debug` keeps the real address: it is
  off by default, and whoever turns it on is chasing a connection problem and
  needs to see which address was tried.

Both routes into the log are covered. The serial leak found in 1.17 came from
a direct log argument; the address leak came the other way round, through an
exception message that the coordinator then logged:

    raise SSCConnectionError(f"No response from {self._host} within ...")

A behavioural test for either would have to drive the whole flow; a scan over
the package sees every call at once, including the ones written next week.
"""

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"

SERIAL = ("serial", "mask_serial")
HOST = ("host", "mask_host")
LEVELS_THAT_REACH_A_SUPPORT_THREAD = {"info", "warning", "error", "exception", "critical"}


def _is_masked(node, mask: str) -> bool:
    """A call to the masking function anywhere inside the argument."""
    return any(
        isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == mask
        for inner in ast.walk(node)
    )


def _mentions(node, term: str) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and term in inner.id.lower():
            return True
        if isinstance(inner, ast.Attribute) and term in inner.attr.lower():
            return True
    return False


def _offends(node, identifier) -> bool:
    term, mask = identifier
    return _mentions(node, term) and not _is_masked(node, mask)


def _log_calls(tree):
    for node in ast.walk(tree):
        is_logger_call = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id.endswith("LOGGER")
        )
        if is_logger_call:
            yield node


def _unmasked_log_arguments(source: str):
    tree = ast.parse(source)
    for node in _log_calls(tree):
        identifiers = [SERIAL]
        if node.func.attr in LEVELS_THAT_REACH_A_SUPPORT_THREAD:
            identifiers.append(HOST)
        for argument in node.args[1:]:
            for identifier in identifiers:
                if _offends(argument, identifier):
                    yield node.lineno, ast.unparse(argument)


def _unmasked_exception_messages(source: str):
    """A host interpolated into a raised exception ends up in the log verbatim."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        for argument in node.exc.args:
            if not isinstance(argument, ast.JoinedStr):
                continue
            for part in argument.values:
                if isinstance(part, ast.FormattedValue) and _offends(part.value, HOST):
                    yield node.lineno, ast.unparse(part.value)


def _findings(scan) -> list[str]:
    return [
        f"{module.name}:{lineno}: {snippet}"
        for module in sorted(PACKAGE.glob("*.py"))
        for lineno, snippet in scan(module.read_text(encoding="utf-8"))
    ]


def test_no_log_call_passes_an_unmasked_identifier():
    offenders = _findings(_unmasked_log_arguments)
    assert not offenders, "log call(s) with an unmasked identifier:\n" + "\n".join(offenders)


def test_no_raised_message_carries_an_unmasked_host():
    offenders = _findings(_unmasked_exception_messages)
    assert not offenders, "exception message(s) with an unmasked host:\n" + "\n".join(offenders)


def test_the_scan_finds_what_it_is_looking_for():
    """Proof-of-red: the guard must fail on the two shapes it exists for."""
    log_leak = 'def f():\n    _LOGGER.warning("at %s", speaker.host)\n'
    raise_leak = 'def f():\n    raise SSCConnectionError(f"No response from {self._host}")\n'
    debug_is_allowed = 'def f():\n    _LOGGER.debug("at %s", speaker.host)\n'

    assert list(_unmasked_log_arguments(log_leak))
    assert list(_unmasked_exception_messages(raise_leak))
    assert not list(_unmasked_log_arguments(debug_is_allowed))
    assert not list(_unmasked_log_arguments(log_leak.replace("speaker.host", "mask_host(x)")))
