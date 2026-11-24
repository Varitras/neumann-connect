"""No CI lane may go on testing an older Home Assistant without saying so.

The test plugin before Home Assistant's own ended, and the latest-version job
stayed green on the last release it supported. So the lanes are held here by
running their steps against made-up answers, not by reading their text alone.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
PLUGIN = "pytest-homeassistant"


def _steps(workflow: str, job: str) -> list[dict]:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    return yaml.safe_load(text)["jobs"][job]["steps"]


def _step(workflow: str, job: str, name: str) -> dict:
    (step,) = [step for step in _steps(workflow, job) if step.get("name") == name]
    return step


# --- what gets installed -----------------------------------------------------


def _installs_the_newest(step: dict) -> bool:
    """The spec follows the plugin, and the command really installs the spec.

    Without the lower bound, a Python too old for the plugin makes pip take an
    unrelated 0.1.x release of the same name instead of failing.
    """
    spec = step.get("env", {}).get("PLUGIN_SPEC", "")
    follows = re.fullmatch(PLUGIN + r">=20\d\d\.\d+", spec) is not None
    return follows and '"$PLUGIN_SPEC"' in step["run"]


def test_the_latest_job_installs_the_newest_plugin():
    installs = [s for s in _steps("ci.yml", "check-latest") if "pip install" in s.get("run", "")]
    assert len(installs) == 1 and _installs_the_newest(installs[0]), installs


@pytest.mark.parametrize(
    ("spec", "command"),
    [
        (PLUGIN + "-custom-component", 'pip install "$PLUGIN_SPEC"'),
        (PLUGIN, 'pip install "$PLUGIN_SPEC"'),
        (PLUGIN + "==2026.11.3", 'pip install "$PLUGIN_SPEC"'),
        (PLUGIN + ">=0.1", 'pip install "$PLUGIN_SPEC"'),
        (PLUGIN + ">=2026.11", "pip install -r requirements_test.txt"),
    ],
)
def test_an_install_that_stops_following_is_refused(spec, command):
    assert not _installs_the_newest({"env": {"PLUGIN_SPEC": spec}, "run": command})


def _pins_the_own_plugin(requirements: str) -> bool:
    return re.search(rf"^{PLUGIN}==20\d\d\.\d+\.\d+$", requirements, re.MULTILINE) is not None


def test_the_pin_is_home_assistants_own_plugin():
    assert _pins_the_own_plugin((REPO / "requirements_test.txt").read_text(encoding="utf-8"))
    assert not _pins_the_own_plugin(f"# {PLUGIN}==2026.11.3\n{PLUGIN}-custom-component==0.13.375\n")


# --- the latest job checks what it got ---------------------------------------


def _run_latest_check(tmp_path, installed: str, answer: str) -> subprocess.CompletedProcess:
    """The job's own step, with a made-up installation and answer from PyPI."""
    step = _step("ci.yml", "check-latest", "The job must run the newest release")
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "python").symlink_to(sys.executable)
    (tmp_path / "answer").write_text(answer, encoding="utf-8")
    (tools / "curl").write_text(f'#!/bin/sh\ncat "{tmp_path}/answer"\n', encoding="utf-8")
    (tools / "curl").chmod(0o755)
    metadata = tmp_path / f"pytest_homeassistant-{installed}.dist-info" / "METADATA"
    metadata.parent.mkdir()
    metadata.write_text(f"Name: {PLUGIN}\nVersion: {installed}\n", encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            **step["env"],
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("installed", "answer", "passes"),
    [
        ("2027.4.1", '{"info": {"version": "2027.4.1"}}', True),
        # A newer release needs a newer Python, or clashes with a pinned tool:
        # pip then installs the older one and reports success.
        ("2027.3.4", '{"info": {"version": "2027.4.1"}}', False),
        ("2027.4.1", "", False),
        ("2027.4.1", '{"message": "Not Found"}', False),
    ],
)
def test_the_latest_job_fails_unless_it_got_the_newest(tmp_path, installed, answer, passes):
    finished = _run_latest_check(tmp_path, installed, answer)
    assert (finished.returncode == 0) is passes, finished.stdout + finished.stderr


# --- the weekly look at the next release -------------------------------------


def _find_next(monkeypatch, tmp_path, home_assistant: list[str], plugin: list[str]) -> dict:
    """The version step of ha-next.yml, with made-up releases on PyPI."""
    (step,) = [s for s in _steps("ha-next.yml", "next") if s.get("id") == "versions"]
    published = {"homeassistant": home_assistant, PLUGIN: plugin}

    def answer(url, timeout):
        releases = {version: [{"yanked": False}] for version in published[url.split("/")[-2]]}
        return io.StringIO(json.dumps({"releases": releases}))

    output = tmp_path / "output"
    monkeypatch.setattr(urllib.request, "urlopen", answer)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    exec(step["run"], {})  # noqa: S102 - the repository's own workflow step
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    ("home_assistant", "plugin", "expected"),
    [
        (["2027.1.0", "2027.2.0b1"], ["2027.1.0", "2027.2.0b1"], ("2027.2.0b1", "true", "false")),
        (["2027.1.0", "2027.2.0b1"], ["2027.1.0"], ("2027.2.0b1", "false", "false")),
        (["2027.2.0b1", "2027.2.0"], ["2027.2.0"], ("2027.2.0", "true", "true")),
        (["2027.9.0", "2027.10.0"], ["2027.9.0"], ("2027.10.0", "false", "true")),
    ],
)
def test_the_next_release_and_its_test_plugin_are_told_apart(
    monkeypatch, tmp_path, home_assistant, plugin, expected
):
    found = _find_next(monkeypatch, tmp_path, home_assistant, plugin)
    assert (found["homeassistant"], found["harness"], found["final"]) == expected


@pytest.mark.parametrize(("final", "exit_code"), [("true", 1), ("false", 0)])
def test_only_a_final_release_without_a_test_plugin_is_red(final, exit_code):
    step = _step("ha-next.yml", "next", "Say what did not run")
    assert step["if"] == "steps.versions.outputs.harness != 'true'"
    assert step["env"]["FINAL"] == "${{ steps.versions.outputs.final }}"
    finished = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={**os.environ, "FINAL": final, "HOMEASSISTANT": "2027.1.0"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert finished.returncode == exit_code, finished.stdout + finished.stderr
