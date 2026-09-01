"""Every button that talks to the speaker holds the action lock.

The speaker answers one request at a time and a button action is a whole
sequence of them. Two actions interleaved leave it half-written, so
`claim_device()` serialises them per config entry and rejects a second
action while one runs.

The lock was added to the four buttons in `button.py`. The fifth button -
the EQ reset - lives in `eq.py` and was missed, which is the sibling shape
this project keeps producing: the named site is fixed, the structurally
identical one next door is not. A guard sees all of them at once.
"""

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "neumann_kh"

LOCK_HELPER = "claim_device"

# A press that provably talks to nothing goes here with its reason. Empty:
# every button in this integration writes to or reads from the device.
EXEMPT: set = set()


def _presses():
    """Every `async_press` in the package, as (module, class, node)."""
    for source_file in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                is_press = (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "async_press"
                )
                if is_press:
                    yield source_file.name, node.name, item


def _claims_the_device(node) -> bool:
    """`self.coordinator.claim_device()` - an attribute, not a bare name."""
    return any(
        isinstance(inner, ast.Attribute) and inner.attr == LOCK_HELPER
        for inner in ast.walk(node)
    )


def test_every_button_press_claims_the_device():
    unguarded = [
        f"{module}::{class_name}"
        for module, class_name, node in _presses()
        if not _claims_the_device(node) and class_name not in EXEMPT
    ]

    assert not unguarded, (
        f"button press(es) without the action lock: {unguarded}. Wrap the "
        f"device work in `async with self.coordinator.{LOCK_HELPER}():` so it "
        "cannot interleave with a backup, discovery or restore."
    )


def test_the_scan_finds_presses_across_modules():
    """A guard that only ever sees button.py would have missed the EQ reset."""
    modules = {module for module, _, _ in _presses()}

    assert len(modules) > 1, (
        f"the scan only sees {modules} - button presses live in more than one "
        "module, so a single-module scan is blind by construction."
    )
