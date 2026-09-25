#!/usr/bin/env python3
"""Break the code on purpose and check that a test notices.

A passing test proves nothing on its own. Every worthless test in this
repository's history passed happily while the thing it named was broken - and
twice during this project a counter-check reported "passed" without having
run what it claimed to run.

So `.github/mutations/plan.json` describes deliberate breakages, and this
script checks that the named test actually fails for each one.

A mutation that SURVIVES means the code was broken and the suite stayed
green: either the test is decorative, or a guard has gone blind and no longer
looks where the code moved.

A mutation whose `find` text is no longer in the file is an ERROR, not a skip:
that is exactly how a harness ends up reporting "all caught" without having
checked anything.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# pytest's exit code for "tests ran and at least one failed". A collection
# error is 2, an unknown node 4, an empty selection 5 - and any of those
# used to pass as "caught" because the check was merely "non-zero".
PYTEST_EXIT_TESTS_FAILED = 1
_FAILED_COUNT = re.compile(r"\b(\d+) failed\b")


def _run_expected_test(node_id: str) -> bool:
    """True if the named test FAILS (which is what a live mutation must do)."""
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", node_id, "-q", "-m", "", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        # A failing run is the expected outcome here, not an error.
        check=False,
    )
    if finished.returncode != PYTEST_EXIT_TESTS_FAILED:
        return False
    # Exit code 1 also covers a fixture that raised, which the summary counts
    # as "error", not "failed" - and an error is not the assertion noticing.
    failed = _FAILED_COUNT.search(finished.stdout)
    return failed is not None and int(failed.group(1)) > 0


def _apply(plan_entry: dict) -> tuple[str, bytes]:
    target = REPO / plan_entry["path"]
    # The backup is the raw bytes. read_text() translates CRLF to LF, so a
    # text backup was already not the original, and every run left the
    # mutated files of a Windows checkout rewritten with LF. The mutation
    # itself works on the translated text: the plan's multi-line `find`
    # strings are written with plain newlines.
    original = target.read_bytes()
    text = target.read_text(encoding="utf-8")
    occurrences = text.count(plan_entry["find"])
    if occurrences != 1:
        raise LookupError(
            f"{plan_entry['name']}: `find` matches {occurrences} times in "
            f"{plan_entry['path']} - the code moved and this mutation checks "
            "nothing. Update the entry."
        )
    target.write_text(text.replace(plan_entry["find"], plan_entry["replace"], 1), encoding="utf-8")
    return str(target), original


def _restore(target: str, original: bytes) -> None:
    pathlib.Path(target).write_bytes(original)


def main(plan_path: str) -> int:
    plan = json.loads(pathlib.Path(plan_path).read_text(encoding="utf-8"))
    survivors: list[str] = []
    stale: list[str] = []

    for entry in plan:
        try:
            target, original = _apply(entry)
        except LookupError as err:
            stale.append(str(err))
            continue
        try:
            caught = _run_expected_test(entry["expect"])
        finally:
            _restore(target, original)
        status = "caught" if caught else "SURVIVED"
        print(f"{status:9} {entry['name']}")
        if not caught:
            survivors.append(f"{entry['name']} (expected {entry['expect']} to fail)")

    print(f"\n{len(plan)} mutations, {len(survivors)} survived, {len(stale)} stale")
    for line in stale + survivors:
        print(f"  ! {line}")
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: mutate.py <plan.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
