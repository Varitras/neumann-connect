"""The guards that watch the guards.

Two failure modes, both real in this family of projects:

  A guard goes BLIND: it scans one source file by name, the code moves to a
  new module, and the scan keeps passing over the file it still knows.

  A guard goes MISSING: deleting a test is a green diff; nothing says the
  protection went with it.

Build rules for every new guard here:
  1. Scan the package (PACKAGE.glob("*.py")), never a single named file.
  2. Prove the guard can fail - feed the detector the exact shape it exists
     to catch, ideally the verbatim line from the incident.
  3. List it in GUARD_FILES with one line saying what it holds.
"""

import ast
import importlib
import pathlib

TESTS = pathlib.Path(__file__).resolve().parent
PACKAGE = TESTS.parents[0] / "custom_components" / "neumann_kh"

GUARD_FILES = {
    "test_budgets.py": "no module grows past its ceiling, no function past its complexity ratchet",
    "test_comment_narration.py": "no comment merely restates the code it sits on",
    "test_constant_owners.py": "no constant is defined in two modules",
    "test_device_writes.py": "every device-writing button goes through the action lock",
    "test_ci_parity.py": "CI runs the same check script a developer runs",
    "test_mutation_harness.py": "the mutation run fails loudly instead of reporting a breakage it never applied",
    "test_log_privacy.py": "no log call hands out a serial number in full",
    "test_guards.py": "the guards stay package-wide and stay present",
}


def test_every_guard_file_is_listed_and_present():
    """Deleting a guard is otherwise a green diff."""
    missing = [
        name
        for name in GUARD_FILES
        if not (TESTS / name).exists()
        or "def test_" not in (TESTS / name).read_text(encoding="utf-8")
    ]

    assert not missing, (
        f"guard file(s) gone or emptied: {missing}. If the protection is "
        "genuinely obsolete, remove the entry here in the same commit and say "
        "in the message what replaced it."
    )


def test_the_package_path_is_real():
    """A guard suite pointed at a moved package scans nothing and stays green
    about it."""
    assert PACKAGE.is_dir() and list(PACKAGE.glob("*.py")), (
        f"{PACKAGE} holds no Python modules - fix PACKAGE here, or every "
        "package-wide guard in this suite is scanning a void."
    )


def test_every_guard_scans_a_real_directory():
    """A guard whose PACKAGE does not resolve scans nothing and passes.

    This happened while adopting the guard templates: the copy still carried
    the placeholder path, `glob` yielded nothing, and the run was green. The
    index test alone cannot catch it - the file exists and has tests.
    """
    void = []
    for name in GUARD_FILES:
        module = importlib.import_module(name.removesuffix(".py"))
        package = getattr(module, "PACKAGE", None)
        if package is not None and not (package.is_dir() and list(package.glob("*.py"))):
            void.append(f"{name} -> {package}")

    assert not void, (
        "guard(s) scanning a void: "
        + ", ".join(void)
        + ". Fix PACKAGE - a guard pointed at a path that does not exist "
        "reports green without having looked at anything."
    )


# A guard that legitimately targets one named file, with the reason. Anything
# that scans the integration itself does NOT belong here.
PINNING_EXEMPT = {
    "test_ci_parity.py": "CI runs the same check script a developer runs",
    "test_mutation_harness.py": "checks the harness script, not the package",
}


def test_no_guard_pins_itself_to_a_single_source_file():
    """The blindness rule, enforced instead of written down.

    A guard that reads one named module keeps passing after the code moves.
    Guards must enumerate the package, so a new or renamed module is covered
    the moment it exists.
    """
    offenders = []
    for name in GUARD_FILES:
        if name in PINNING_EXEMPT:
            continue
        tree = ast.parse((TESTS / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # PACKAGE / "some_module.py" - a literal module name joined onto
            # the package path is the shape that goes blind.
            is_path_join = isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            if not is_path_join:
                continue
            right = node.right
            if isinstance(right, ast.Constant) and str(right.value).endswith(".py"):
                offenders.append(f"{name}: PACKAGE / {right.value!r}")

    assert not offenders, (
        "guard(s) pinned to a single source file: "
        + ", ".join(offenders)
        + ". Use PACKAGE.glob('*.py') - a pinned scan goes blind on the next "
        "move and the suite stays green."
    )
