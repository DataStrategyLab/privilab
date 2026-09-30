"""Import and command boundaries must remain offline without explicit opt-in."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from privilab.evals import live_openai

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("gate", [None, "", "0", "true", "yes", " 1"])
def test_direct_runner_requires_exact_gate(
    gate: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRIVILAB_LIVE_EVAL", raising=False)
    if gate is not None:
        monkeypatch.setenv("PRIVILAB_LIVE_EVAL", gate)
    with pytest.raises(ValueError, match="requires PRIVILAB_LIVE_EVAL=1"):
        live_openai.run_live(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("execute", [False, True])
def test_import_and_direct_module_never_touch_credentials_files_or_network(
    execute: bool,
) -> None:
    # Import everything first so guards measure only module import/execution.
    script = """
import os, pathlib, runpy, socket
import privilab.application, privilab.adapters.storage, privilab.adapters.retrieval
import privilab.application.run_review, privilab.application.telemetry
original = type(os.environ).__getitem__
def environment(self, name):
    if name == "OPENAI_API_KEY":
        raise AssertionError("credential read before live gate")
    return original(self, name)
def forbidden(*args, **kwargs):
    raise AssertionError("side effect before live gate")
type(os.environ).__getitem__ = environment
socket.create_connection = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
pathlib.Path.open = forbidden
"""
    script += (
        'runpy.run_module("privilab.evals.live_openai", run_name="__main__")'
        if execute
        else "import privilab.evals.live_openai"
    )
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("PRIVILAB_LIVE_EVAL", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (1 if execute else 0)
    assert "AssertionError" not in result.stderr
    if execute:
        assert result.stderr.strip() == "live evaluation requires PRIVILAB_LIVE_EVAL=1"


def test_make_targets_keep_live_execution_outside_ci() -> None:
    result = subprocess.run(
        ["make", "-n", "ci-stages"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "live_openai" not in result.stdout and "eval-live" not in result.stdout
    text = (ROOT / "Makefile").read_text()
    assert "ci: guard" in text
    assert "$(MAKE) --no-print-directory ci-stages" in text
    assert 'PRIVILAB_LIVE_EVAL=1 "$(PYTHON)" -m privilab.evals.live_openai' in text
    assert "OPENAI_API_KEY" not in text
