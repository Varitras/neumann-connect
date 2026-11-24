"""The gitleaks pin check does not depend on GitHub's API limit.

GitHub answers unauthenticated API requests only so often per address, and
CI runners share addresses. The check failed on such a 403 while the pin was
current.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_gitleaks_pin.py"
RELEASES = "https://github.com/gitleaks/gitleaks/releases"


def _load():
    spec = importlib.util.spec_from_file_location("check_gitleaks_pin", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _refuse(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 403, "rate limit exceeded", Message(), io.BytesIO())


class _Page(io.BytesIO):
    """The answer to a request GitHub redirected to `url`."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url


@pytest.fixture
def github(monkeypatch):
    """GitHub's answers: where the latest page leads, and what the API says."""
    answers = {"page": f"{RELEASES}/tag/v9.1.0", "api": None}

    def urlopen(request, timeout):
        url = request if isinstance(request, str) else request.full_url
        if url.startswith("https://api.github.com/"):
            if answers["api"] is None:
                raise _refuse(url)
            return io.BytesIO(json.dumps(answers["api"]).encode())
        assert url == f"{RELEASES}/latest"
        if answers["page"] is None:
            raise _refuse(url)
        return _Page(answers["page"])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return answers


def _check(monkeypatch, tmp_path, pinned: str) -> int:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(f'GITLEAKS_VERSION: "{pinned}"\n', encoding="utf-8")
    module = _load()
    monkeypatch.setattr(module, "WORKFLOW", workflow)
    return module.main()


def test_a_current_pin_passes_while_the_api_refuses(github, monkeypatch, tmp_path):
    assert _check(monkeypatch, tmp_path, "9.1.0") == 0


def test_an_old_pin_fails_while_the_api_refuses(github, monkeypatch, tmp_path, capsys):
    assert _check(monkeypatch, tmp_path, "9.0.0") == 1
    message = capsys.readouterr().err
    assert '"9.1.0"' in message and "the digest GitHub shows" in message


def test_an_old_pin_names_the_new_digest(github, monkeypatch, tmp_path, capsys):
    asset = {"name": "gitleaks_9.1.0_linux_x64.tar.gz", "digest": "sha256:abc123"}
    github["api"] = {"tag_name": "v9.1.0", "assets": [asset]}
    assert _check(monkeypatch, tmp_path, "9.0.0") == 1
    assert '"abc123"' in capsys.readouterr().err


@pytest.mark.parametrize("page", [None, RELEASES, f"{RELEASES}/tag/nightly"])
def test_an_answer_that_names_no_release_fails(github, monkeypatch, tmp_path, page):
    github["page"] = page
    assert _check(monkeypatch, tmp_path, "9.1.0") == 1
