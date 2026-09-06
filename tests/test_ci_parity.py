"""CI and the local check script stay one definition of done.

Two lists of commands are two definitions, and they drift without anyone
noticing: a gate added in one place simply does not exist in the other, and
the run that matters is whichever one you did not look at.

So the workflow calls `check.sh` and nothing else, and these tests fail if a
tool invocation reappears in the workflow, if the script stops invoking one,
or if the script is committed without its executable bit - which would fail
in CI with "Permission denied" and nowhere else.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
CHECK_SCRIPT = REPO / ".github" / "scripts" / "check.sh"

# Tools whose invocation belongs to check.sh alone.
OWNED_BY_THE_SCRIPT = ("ruff", "pytest", "mutate.py")


def _run_commands(workflow_text: str) -> list[str]:
    """Every `run:` command of every job.

    Parsed, not grepped: a step written as `run: |` carries its commands on
    the following lines, so a line scan for "- run:" sees the pipe and misses
    everything the step actually does.
    """
    workflow = yaml.safe_load(workflow_text)
    return [
        step["run"]
        for job in workflow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and "run" in step
    ]


def _steps() -> list[str]:
    return _run_commands(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_calls_the_check_script():
    assert any("check.sh" in step for step in _steps()), (
        "no CI step runs .github/scripts/check.sh - the pipeline and the "
        "local definition of done have parted ways."
    )


def test_the_workflow_does_not_invoke_the_tools_itself():
    offenders = [
        step
        for step in _steps()
        if "check.sh" not in step
        and any(re.search(rf"\b{tool}\b", step) for tool in OWNED_BY_THE_SCRIPT)
    ]

    assert not offenders, (
        f"CI step(s) running a tool directly: {offenders}. Put the gate in "
        "check.sh instead, or the two lists drift and only one of them is the "
        "one you ran."
    )


def test_the_check_script_still_invokes_every_tool_it_owns():
    """The other direction: a gate quietly dropped from the script."""
    script = CHECK_SCRIPT.read_text(encoding="utf-8")
    missing = [tool for tool in OWNED_BY_THE_SCRIPT if tool not in script]

    assert not missing, (
        f"check.sh no longer mentions {missing}. If a gate is genuinely gone, "
        "drop it from OWNED_BY_THE_SCRIPT in the same commit."
    )


def test_the_scripts_are_committed_executable():
    """A 100644 shell script fails in CI only, with 'Permission denied'."""
    listing = subprocess.run(
        ["git", "ls-files", "-s", ".github/scripts"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    not_executable = [
        line.split("\t")[-1]
        for line in listing.splitlines()
        if line and not line.startswith("100755")
    ]

    assert not not_executable, (
        f"script(s) committed without the executable bit: {not_executable}. "
        "Fix with `git update-index --chmod=+x <path>`."
    )


def test_the_scan_reads_block_style_steps_too():
    """Proof-of-red: the shape a line scan for "- run:" walks straight past."""
    block_style = """
jobs:
  something:
    steps:
      - name: run the tests by hand
        run: |
          python -m pytest tests/ -q
"""
    commands = _run_commands(block_style)

    assert commands, "a block-style run step must be seen at all"
    assert any("pytest" in command for command in commands)


def test_no_shell_script_carries_carriage_returns():
    r"""A single \r makes /bin/sh refuse the file: "bad interpreter".

    .gitattributes keeps the checkout clean, but any tool that rewrites a
    script in text mode on Windows puts them back - and the breakage shows up
    only when someone runs it, with an error naming an interpreter rather
    than the file.
    """
    scripts = sorted((REPO / ".github" / "scripts").glob("*.sh"))
    offenders = [
        script.name for script in scripts if script.is_file() and b"\r" in script.read_bytes()
    ]

    assert not offenders, (
        f"shell script(s) with CRLF line endings: {offenders}. Rewrite them "
        "with LF - .gitattributes keeps the checkout right, an editor writing "
        "in text mode does not."
    )
