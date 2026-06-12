"""Unit tests for pi harness detection/rendering in skill_runner (ADR-336)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from lib import skill_runner  # noqa: E402

_HARNESS_ENV = [
    "COGNITIVE_OS_HARNESS",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_MCP_SERVER",
    "CODEX_PROJECT_DIR",
    "CODEX_SESSION_ID",
    "PI_SESSION_ID",
    "PI_PROJECT_DIR",
]


def _clear(monkeypatch):
    for key in _HARNESS_ENV:
        monkeypatch.delenv(key, raising=False)


class TestPiHarnessDetection:
    def test_detects_pi_via_session_id(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("PI_SESSION_ID", "019eb3f7-2630-75c3")
        assert skill_runner.detect_harness() == "pi"

    def test_detects_pi_via_project_dir(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("PI_PROJECT_DIR", "/work/repo")
        assert skill_runner.detect_harness() == "pi"

    def test_explicit_override_wins(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("COGNITIVE_OS_HARNESS", "pi")
        assert skill_runner.detect_harness() == "pi"

    def test_claude_still_precedes_pi(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/repo")
        monkeypatch.setenv("PI_SESSION_ID", "x")
        assert skill_runner.detect_harness() == "claude_code"


class TestPiSkillRender:
    def test_run_skill_pi_renders_body(self, tmp_path):
        skill_dir = tmp_path / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: demo\n---\nHello {{who}}\n",
            encoding="utf-8",
        )
        result = skill_runner.run_skill(
            "demo-skill",
            args={"who": "pi"},
            harness="pi",
            skills_root=tmp_path / "skills",
        )
        assert result.success
        assert result.harness == "pi"
        assert "Hello pi" in result.rendered
