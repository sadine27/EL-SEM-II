"""SP8 — string-level invariants for the Dockerfile."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DF = ROOT / "Dockerfile"
ENTRY = ROOT / "docker-entrypoint.sh"


def _contents() -> str:
    return DF.read_text(encoding="utf-8")


def test_dockerfile_exists():
    assert DF.exists()


def test_multi_stage_build():
    text = _contents()
    assert text.count("FROM ") >= 2, "Dockerfile must be multi-stage"
    assert "AS builder" in text or "as builder" in text


def test_base_image_pinned_to_python_312_slim():
    assert "python:3.12-slim" in _contents()


def test_runs_as_non_root_before_cmd():
    text = _contents()
    user_idx = text.lower().rfind("\nuser ")
    cmd_idx = text.lower().rfind("\ncmd ")
    assert user_idx > -1, "no USER directive"
    assert cmd_idx > -1, "no CMD directive"
    assert user_idx < cmd_idx, "USER must precede CMD"
    assert "appuser" in text


def test_no_add_directive():
    text = _contents()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.lower().startswith("add "), f"forbidden ADD: {line!r}"


def test_apt_install_uses_no_install_recommends():
    text = _contents()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "apt-get install" in line and "--no-install-recommends" not in line:
            tail = " ".join(lines[i:i + 4])
            assert "--no-install-recommends" in tail, (
                f"apt-get install without --no-install-recommends: {line!r}"
            )


def test_entrypoint_script_exists_and_execs_verify_env():
    assert ENTRY.exists()
    body = ENTRY.read_text(encoding="utf-8")
    assert "verify_env_runtime.py" in body
    assert 'exec "$@"' in body
