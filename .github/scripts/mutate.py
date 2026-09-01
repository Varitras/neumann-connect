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
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


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
    return finished.returncode != 0


def _apply(plan_entry: dict) -> tuple[str, str]:
    target = REPO / plan_entry["path"]
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(plan_entry["find"])
    if occurrences != 1:
        raise LookupError(
            f"{plan_entry['name']}: `find` matches {occurrences} times in "
            f"{plan_entry['path']} - the code moved and this mutation checks "
            "nothing. Update the entry."
        )
    target.write_text(original.replace(plan_entry["find"], plan_entry["replace"], 1), encoding="utf-8")
    return str(target), original


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
            pathlib.Path(target).write_text(original, encoding="utf-8")
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
