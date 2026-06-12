"""Unit tests for scripts/cos_init.py — Phase 2.1 + 2.2 + 2.3 bootstrap.

Phase 2.1: detect_harness() port from scripts/_lib/settings-driver.sh::cos_detect_harness.
Phase 2.2: scope_allows() and skill_scope_allows() ports from scripts/cos-init.sh.
Phase 2.3: install_rule(), install_hook(), install_skill_dir() ports from scripts/cos-init.sh.
Tests are pure Python (no subprocess) except the end-to-end reinstall-sweep
test, which runs the full installer against a temp project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable without hyphens (snake_case filename per rules/python-naming.md)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import cos_init

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestDetectHarnessClaude:
    def test_claude_dir_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only .claude/settings.json exists, detect_harness returns 'claude'."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "claude"

    def test_default_is_claude(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no markers are present and no env vars set, default is 'claude'."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "claude"

    def test_both_dirs_present_defaults_to_claude_without_install_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both .claude/settings.json AND .codex/hooks.json exist, neither
        marker-only branch wins — falls through to default 'claude'."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "hooks.json").write_text("{}")
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "claude"

    def test_install_metadata_resolves_dual_marker_projects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Install metadata preserves the selected harness during migrations."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "hooks.json").write_text("{}")
        (tmp_path / ".cognitive-os").mkdir()
        (tmp_path / ".cognitive-os" / "install-meta.json").write_text(
            '{"harness": "codex", "settings_driver": ".codex/hooks.json"}'
        )
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "codex"


class TestDetectHarnessCodex:
    def test_codex_dir_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only .codex/hooks.json exists, detect_harness returns 'codex'."""
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "hooks.json").write_text("{}")
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "codex"

    def test_codex_env_project_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEX_PROJECT_DIR env var triggers codex detection."""
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "codex"

    def test_codex_env_session_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEX_SESSION_ID env var triggers codex detection."""
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.setenv("CODEX_SESSION_ID", "sess-abc123")
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "codex"

    def test_codex_env_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEX_HOME env var triggers codex detection."""
        monkeypatch.delenv("COGNITIVE_OS_HARNESS", raising=False)
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.setenv("CODEX_HOME", "/workspace/codex-home")
        assert cos_init.detect_harness(str(tmp_path)) == "codex"


class TestDetectHarnessExplicitOverride:
    def test_env_override_beats_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COGNITIVE_OS_HARNESS env var wins over filesystem markers."""
        # Set up claude markers to confirm env override beats them
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        monkeypatch.setenv("COGNITIVE_OS_HARNESS", "codex")
        monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert cos_init.detect_harness(str(tmp_path)) == "codex"

    def test_env_override_explicit_claude(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COGNITIVE_OS_HARNESS=claude works as an explicit override."""
        monkeypatch.setenv("COGNITIVE_OS_HARNESS", "claude")
        assert cos_init.detect_harness(str(tmp_path)) == "claude"


# ── Phase 2.2: scope_allows() unit tests ─────────────────────────────

class TestScopeAllows:
    def test_install_scope_all_always_allows(self, tmp_path: Path) -> None:
        """install_scope='all' skips all filtering — every file passes."""
        f = tmp_path / "test.sh"
        f.write_text("# SCOPE: os-only\n# rest\n")
        assert cos_init.scope_allows(str(f), install_scope="all") is True

    def test_no_scope_header_is_universal(self, tmp_path: Path) -> None:
        """Files with no SCOPE header are always included (untagged = universal)."""
        f = tmp_path / "no_header.sh"
        f.write_text("#!/bin/bash\n# just a script\necho hello\n")
        assert cos_init.scope_allows(str(f), install_scope="both") is True

    def test_hash_scope_project_allowed_under_both(self, tmp_path: Path) -> None:
        """# SCOPE: project is allowed when install_scope=both."""
        f = tmp_path / "project_rule.md"
        f.write_text("# SCOPE: project\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="both") is True

    def test_hash_scope_both_allowed_under_project(self, tmp_path: Path) -> None:
        """# SCOPE: both is allowed when install_scope=project."""
        f = tmp_path / "both_rule.sh"
        f.write_text("# SCOPE: both\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="project") is True

    def test_hash_scope_os_only_blocked_under_both(self, tmp_path: Path) -> None:
        """# SCOPE: os-only is blocked when install_scope=both."""
        f = tmp_path / "os_only.sh"
        f.write_text("# SCOPE: os-only\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="both") is False

    def test_html_scope_project_allowed(self, tmp_path: Path) -> None:
        """<!-- SCOPE: project --> HTML form is parsed and allowed under project install."""
        f = tmp_path / "doc.md"
        f.write_text("<!-- SCOPE: project -->\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="project") is True

    def test_html_scope_os_only_blocked(self, tmp_path: Path) -> None:
        """<!-- SCOPE: os-only --> HTML form is blocked under both install."""
        f = tmp_path / "os_doc.md"
        f.write_text("<!-- SCOPE: os-only -->\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="both") is False

    def test_nonexistent_file_passes(self, tmp_path: Path) -> None:
        """Non-existent paths pass the filter (matches bash: [ -f ] || return 0)."""
        assert cos_init.scope_allows(str(tmp_path / "nonexistent.sh"), install_scope="both") is True

    def test_unknown_scope_tag_passes(self, tmp_path: Path) -> None:
        """Unknown SCOPE tags are permissive — file is included."""
        f = tmp_path / "weird.sh"
        f.write_text("# SCOPE: experimental\n# content\n")
        assert cos_init.scope_allows(str(f), install_scope="both") is True

    def test_scope_only_checked_in_first_3_lines(self, tmp_path: Path) -> None:
        """SCOPE header on line 4 is ignored — only first 3 lines scanned."""
        f = tmp_path / "late_header.sh"
        f.write_text("line1\nline2\nline3\n# SCOPE: os-only\n")
        # os-only on line 4 should NOT be detected → file passes
        assert cos_init.scope_allows(str(f), install_scope="both") is True


# ── Phase 2.2: skill_scope_allows() unit tests ───────────────────────

class TestSkillScopeAllows:
    def _make_skill(self, skill_dir: Path, frontmatter: str) -> None:
        """Write a minimal SKILL.md with the given frontmatter line."""
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n# Skill\n")

    def test_install_scope_all_always_allows(self, tmp_path: Path) -> None:
        """install_scope='all' skips filtering — even os-only skills pass."""
        skill_dir = tmp_path / "my-skill"
        self._make_skill(skill_dir, "audience: os-only")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="all") is True

    def test_missing_skill_md_passes(self, tmp_path: Path) -> None:
        """Missing SKILL.md → allow (matches bash: [ -f ] || return 0)."""
        skill_dir = tmp_path / "no-skill-md"
        skill_dir.mkdir()
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_audience_both_is_allowed(self, tmp_path: Path) -> None:
        """audience: both → True under any install_scope."""
        skill_dir = tmp_path / "skill-both"
        self._make_skill(skill_dir, "audience: both")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_audience_project_is_allowed(self, tmp_path: Path) -> None:
        """audience: project → True under project install_scope."""
        skill_dir = tmp_path / "skill-project"
        self._make_skill(skill_dir, "audience: project")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="project") is True

    def test_audience_adopters_is_allowed(self, tmp_path: Path) -> None:
        """audience: adopters → True (per bash mapping — external adopters)."""
        skill_dir = tmp_path / "skill-adopters"
        self._make_skill(skill_dir, "audience: adopters")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_audience_human_is_allowed(self, tmp_path: Path) -> None:
        """audience: human → True (human-facing skill is project-installable)."""
        skill_dir = tmp_path / "skill-human"
        self._make_skill(skill_dir, "audience: human")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_audience_os_only_is_blocked(self, tmp_path: Path) -> None:
        """audience: os-only → False under project install_scope."""
        skill_dir = tmp_path / "skill-os-only"
        self._make_skill(skill_dir, "audience: os-only")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="project") is False

    def test_audience_os_dev_is_blocked(self, tmp_path: Path) -> None:
        """audience: os-dev → False under both install_scope."""
        skill_dir = tmp_path / "skill-os-dev"
        self._make_skill(skill_dir, "audience: os-dev")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False

    def test_scope_field_fallback(self, tmp_path: Path) -> None:
        """scope: field (not audience:) is also parsed."""
        skill_dir = tmp_path / "skill-scope-field"
        self._make_skill(skill_dir, "scope: os-only")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False

    def test_no_audience_field_passes(self, tmp_path: Path) -> None:
        """SKILL.md with no audience/scope field → allow."""
        skill_dir = tmp_path / "skill-no-field"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ntitle: My Skill\n---\n# Skill\n")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_scope_marker_os_only_overrides_audience_both(self, tmp_path: Path) -> None:
        """Canonical SCOPE marker blocks project install even when legacy audience says both."""
        skill_dir = tmp_path / "skill-marker-os-only"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("<!-- SCOPE: os-only -->\n---\naudience: both\n---\n# Skill\n")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="project") is False

    def test_scope_marker_both_overrides_audience_os_only(self, tmp_path: Path) -> None:
        """Canonical SCOPE marker allows project install when legacy audience is stale."""
        skill_dir = tmp_path / "skill-marker-both"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("<!-- SCOPE: both -->\n---\naudience: os-only\n---\n# Skill\n")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="project") is True

    def test_scope_field_in_body_prose_does_not_classify(self, tmp_path: Path) -> None:
        """L-3: legacy audience/scope fallback scans the YAML frontmatter ONLY.

        A body line like `scope: os` (e.g. inside a code example) must not
        classify a marker-less skill os-only — the reinstall sweep would then
        delete it from consumer projects."""
        skill_dir = tmp_path / "skill-body-scope"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: doc-skill\n---\n# Skill\n\nExample config:\n\n"
            "scope: os\naudience: os-only\n"
        )
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_scope_field_in_frontmatter_still_classifies(self, tmp_path: Path) -> None:
        """L-3 guard: the frontmatter-only restriction keeps parsing real fields."""
        skill_dir = tmp_path / "skill-fm-scope"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: x\nscope: os-only\n---\n# Skill\n"
        )
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False


# ── Phase 2.3: install_rule() unit tests ─────────────────────────────

class TestInstallRule:
    def _make_source(self, src_dir: Path, name: str, content: str = "# rule") -> Path:
        src_dir.mkdir(parents=True, exist_ok=True)
        f = src_dir / f"{name}.md"
        f.write_text(content)
        return f

    def test_symlink_mode_installs_to_single_dest(self, tmp_path: Path) -> None:
        """install_rule copies the rule file to the destination directory."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        self._make_source(src, "trust-score")
        dest.mkdir()
        status = cos_init.install_rule("trust-score", str(src), [str(dest)])
        assert status == "installed"
        assert (dest / "trust-score.md").is_file()

    def test_copy_mode_installs_to_multiple_dests(self, tmp_path: Path) -> None:
        """install_rule copies to all provided destination directories."""
        src = tmp_path / "src"
        dest1 = tmp_path / "dest1"
        dest2 = tmp_path / "dest2"
        self._make_source(src, "adaptive-bypass")
        dest1.mkdir()
        dest2.mkdir()
        status = cos_init.install_rule("adaptive-bypass", str(src), [str(dest1), str(dest2)])
        assert status == "installed"
        assert (dest1 / "adaptive-bypass.md").is_file()
        assert (dest2 / "adaptive-bypass.md").is_file()

    def test_missing_source_returns_skipped(self, tmp_path: Path) -> None:
        """Source file missing → 'skipped' (matches bash: [ -f ] || return)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        status = cos_init.install_rule("nonexistent", str(src), [str(dest)])
        assert status == "skipped"
        assert not (dest / "nonexistent.md").exists()

    def test_target_dir_created_if_missing(self, tmp_path: Path) -> None:
        """Destination directory is created automatically if it does not exist."""
        src = tmp_path / "src"
        self._make_source(src, "token-economy")
        dest = tmp_path / "deep" / "nested" / "dest"
        # dest does NOT exist yet
        status = cos_init.install_rule("token-economy", str(src), [str(dest)])
        assert status == "installed"
        assert (dest / "token-economy.md").is_file()

    def test_idempotent_reinstall(self, tmp_path: Path) -> None:
        """Re-installing over an existing file succeeds without error."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        self._make_source(src, "definition-of-done", "# v1")
        dest.mkdir()
        cos_init.install_rule("definition-of-done", str(src), [str(dest)])
        # Overwrite source and reinstall
        (src / "definition-of-done.md").write_text("# v2")
        status = cos_init.install_rule("definition-of-done", str(src), [str(dest)])
        assert status == "installed"
        assert (dest / "definition-of-done.md").read_text() == "# v2"

    def test_content_preserved(self, tmp_path: Path) -> None:
        """Rule file content is preserved exactly after copy."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        content = "# Trust Score\n\nSome content.\n"
        self._make_source(src, "trust-score", content)
        dest.mkdir()
        cos_init.install_rule("trust-score", str(src), [str(dest)])
        assert (dest / "trust-score.md").read_text() == content


# ── Phase 2.3: install_hook() unit tests ─────────────────────────────

class TestInstallHook:
    def _make_source(self, src_dir: Path, name: str, content: str = "#!/bin/bash\necho hi\n") -> Path:
        src_dir.mkdir(parents=True, exist_ok=True)
        f = src_dir / f"{name}.sh"
        f.write_text(content)
        return f

    def test_installs_hook_to_dest(self, tmp_path: Path) -> None:
        """install_hook copies the hook file to the destination directory."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        self._make_source(src, "auto-refine")
        dest.mkdir()
        status = cos_init.install_hook("auto-refine", str(src), str(dest))
        assert status == "installed"
        assert (dest / "auto-refine.sh").is_file()

    def test_executable_bit_set_on_sh_file(self, tmp_path: Path) -> None:
        """install_hook sets executable bit on the installed .sh file."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        self._make_source(src, "error-learning")
        dest.mkdir()
        cos_init.install_hook("error-learning", str(src), str(dest))
        installed = dest / "error-learning.sh"
        assert os.access(str(installed), os.X_OK), "Installed hook should be executable"

    def test_missing_source_returns_skipped(self, tmp_path: Path) -> None:
        """Source file missing → 'skipped' (matches bash: [ -f ] || return)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        status = cos_init.install_hook("nonexistent", str(src), str(dest))
        assert status == "skipped"
        assert not (dest / "nonexistent.sh").exists()

    def test_target_dir_created_if_missing(self, tmp_path: Path) -> None:
        """Destination directory is created automatically if it does not exist."""
        src = tmp_path / "src"
        self._make_source(src, "dod-gate")
        dest = tmp_path / "deep" / "hooks"
        status = cos_init.install_hook("dod-gate", str(src), str(dest))
        assert status == "installed"
        assert (dest / "dod-gate.sh").is_file()

    def test_idempotent_reinstall(self, tmp_path: Path) -> None:
        """Re-installing over an existing hook succeeds without error."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        self._make_source(src, "blast-radius", "#!/bin/bash\n# v1\n")
        dest.mkdir()
        cos_init.install_hook("blast-radius", str(src), str(dest))
        (src / "blast-radius.sh").write_text("#!/bin/bash\n# v2\n")
        status = cos_init.install_hook("blast-radius", str(src), str(dest))
        assert status == "installed"
        assert (dest / "blast-radius.sh").read_text() == "#!/bin/bash\n# v2\n"

    def test_content_preserved(self, tmp_path: Path) -> None:
        """Hook file content is preserved exactly after copy."""
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        content = "#!/bin/bash\n# test hook\necho done\n"
        self._make_source(src, "session-init", content)
        dest.mkdir()
        cos_init.install_hook("session-init", str(src), str(dest))
        assert (dest / "session-init.sh").read_text() == content


# ── Phase 2.3: install_skill_dir() unit tests ────────────────────────

class TestInstallSkillDir:
    def _make_skill(self, skills_src: Path, name: str, audience: str = "project") -> Path:
        """Create a minimal skill directory with SKILL.md."""
        skill_dir = skills_src / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"---\naudience: {audience}\n---\n# Skill\n")
        (skill_dir / "README.md").write_text(f"# {name}\n")
        return skill_dir

    def test_installs_to_kernel_and_creates_driver_symlink(self, tmp_path: Path) -> None:
        """install_skill_dir copies to kernel and creates relative symlink in driver."""
        src = tmp_path / "skills"
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        skill_dir = self._make_skill(src, "plan-feature")
        kernel.mkdir(parents=True)
        driver.mkdir(parents=True)
        status = cos_init.install_skill_dir(str(skill_dir), str(kernel), str(driver))
        assert status == "installed"
        assert (kernel / "plan-feature" / "SKILL.md").is_file()
        assert (driver / "plan-feature").is_symlink()

    def test_full_copy_mode_copies_contents(self, tmp_path: Path) -> None:
        """Skill directory is fully copied to kernel dest (all files preserved)."""
        src = tmp_path / "skills"
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        skill_dir = self._make_skill(src, "exhaustive-prompt")
        # Add a subdirectory
        (skill_dir / "examples").mkdir()
        (skill_dir / "examples" / "sample.md").write_text("example")
        kernel.mkdir()
        driver.mkdir()
        cos_init.install_skill_dir(str(skill_dir), str(kernel), str(driver))
        assert (kernel / "exhaustive-prompt" / "examples" / "sample.md").is_file()

    def test_scope_filtered_returns_skipped(self, tmp_path: Path) -> None:
        """Skill with audience: os-only → 'skipped' (not installed)."""
        src = tmp_path / "skills"
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        skill_dir = self._make_skill(src, "os-internal", audience="os-only")
        kernel.mkdir()
        driver.mkdir()
        status = cos_init.install_skill_dir(
            str(skill_dir), str(kernel), str(driver), install_scope="both"
        )
        assert status == "skipped"
        assert not (kernel / "os-internal").exists()

    def test_missing_source_dir_returns_error(self, tmp_path: Path) -> None:
        """Source directory does not exist → 'error'."""
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        kernel.mkdir()
        driver.mkdir()
        status = cos_init.install_skill_dir(
            str(tmp_path / "nonexistent-skill"),
            str(kernel),
            str(driver),
        )
        assert status == "error"

    def test_target_dirs_created_if_missing(self, tmp_path: Path) -> None:
        """Kernel and driver destination directories are created if they don't exist."""
        src = tmp_path / "skills"
        kernel = tmp_path / "deep" / "kernel"
        driver = tmp_path / "deep" / "driver"
        skill_dir = self._make_skill(src, "compose-prompt")
        # Neither kernel nor driver exist yet
        status = cos_init.install_skill_dir(str(skill_dir), str(kernel), str(driver))
        assert status == "installed"
        assert (kernel / "compose-prompt" / "SKILL.md").is_file()

    def test_idempotent_reinstall(self, tmp_path: Path) -> None:
        """Re-installing an already installed skill succeeds without error."""
        src = tmp_path / "skills"
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        skill_dir = self._make_skill(src, "agent-dashboard")
        kernel.mkdir()
        driver.mkdir()
        cos_init.install_skill_dir(str(skill_dir), str(kernel), str(driver))
        # Add a new file and reinstall
        (skill_dir / "extra.md").write_text("extra")
        status = cos_init.install_skill_dir(str(skill_dir), str(kernel), str(driver))
        assert status == "installed"
        assert (kernel / "agent-dashboard" / "extra.md").is_file()


# ── os-only marker below frontmatter + reinstall cleanup + catalog filter ──

class TestSkillScopeMarkerBelowFrontmatter:
    """The SCOPE marker sits below the YAML frontmatter in real skills
    (e.g. skills/cos-status/SKILL.md line ~30). A head-window scan missed it
    and shipped os-only skills into consumer projects."""

    def _make_skill(self, root: Path, name: str, body: str) -> Path:
        skill_dir = root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(body)
        return skill_dir

    def test_marker_below_long_frontmatter_blocked(self, tmp_path: Path) -> None:
        """os-only marker after 25 frontmatter lines is honored."""
        frontmatter = "\n".join(f"key{i}: value{i}" for i in range(25))
        body = f"---\nname: cos-status\naudience: both\n{frontmatter}\n---\n\n<!-- SCOPE: os-only -->\n\n# Skill\n"
        skill_dir = self._make_skill(tmp_path, "cos-status", body)
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False

    def test_real_cos_status_skill_blocked(self) -> None:
        """The actual skills/cos-status (verified in-the-wild leak) is filtered."""
        skill_dir = PROJECT_ROOT / "skills" / "cos-status"
        if not (skill_dir / "SKILL.md").is_file():
            pytest.skip("skills/cos-status not present")
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False

    def test_prose_mention_of_marker_not_treated_as_marker(self, tmp_path: Path) -> None:
        """A mid-line mention (documentation prose) must not filter the skill."""
        body = (
            "---\nname: doc-skill\naudience: both\n---\n\n<!-- SCOPE: both -->\n\n"
            "# Skill\nUse the `<!-- SCOPE: os-only -->` marker to keep a skill internal.\n"
        )
        skill_dir = self._make_skill(tmp_path, "doc-skill", body)
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is True

    def test_first_standalone_marker_wins(self, tmp_path: Path) -> None:
        """A code-example standalone marker later in the file does not override
        the skill's own marker (mirrors skills/add-rule)."""
        body = (
            "---\nname: add-rule-like\n---\n\n<!-- SCOPE: os-only -->\n\n# Skill\n"
            "Example template:\n\n<!-- SCOPE: both -->\n"
        )
        skill_dir = self._make_skill(tmp_path, "add-rule-like", body)
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="both") is False

    def test_install_scope_all_keeps_os_only_marker_skill(self, tmp_path: Path) -> None:
        body = "---\nname: x\n---\n<!-- SCOPE: os-only -->\n# Skill\n"
        skill_dir = self._make_skill(tmp_path, "x", body)
        assert cos_init.skill_scope_allows(str(skill_dir), install_scope="all") is True


class TestRemoveStaleOsOnlySkills:
    """Reinstall over a project seeded by an older installer removes os-only skills."""

    def _seed_installed_skill(self, kernel: Path, driver: Path, name: str, body: str) -> None:
        skill = kernel / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(body)
        driver.mkdir(parents=True, exist_ok=True)
        (driver / name).symlink_to(f"../../.cognitive-os/skills/cos/{name}")

    def test_removes_os_only_skill_and_driver_symlink(self, tmp_path: Path) -> None:
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        self._seed_installed_skill(
            kernel, driver, "cos-status",
            "---\nname: cos-status\naudience: both\n---\n<!-- SCOPE: os-only -->\n# Skill\n",
        )
        self._seed_installed_skill(
            kernel, driver, "compose-prompt",
            "---\nname: compose-prompt\naudience: both\n---\n<!-- SCOPE: both -->\n# Skill\n",
        )
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == ["cos-status"]
        assert not (kernel / "cos-status").exists()
        assert not (driver / "cos-status").is_symlink()
        assert (kernel / "compose-prompt" / "SKILL.md").is_file()
        assert (driver / "compose-prompt").is_symlink()

    def test_idempotent_second_run_removes_nothing(self, tmp_path: Path) -> None:
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        self._seed_installed_skill(
            kernel, driver, "victim",
            "---\nname: victim\n---\n<!-- SCOPE: os-only -->\n# Skill\n",
        )
        assert cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both") == ["victim"]
        assert cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both") == []

    def test_install_scope_all_is_noop(self, tmp_path: Path) -> None:
        kernel = tmp_path / "kernel"
        driver = tmp_path / "driver"
        self._seed_installed_skill(
            kernel, driver, "os-skill",
            "---\nname: os-skill\n---\n<!-- SCOPE: os-only -->\n# Skill\n",
        )
        assert cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "all") == []
        assert (kernel / "os-skill").is_dir()

    def test_missing_kernel_dir_is_noop(self, tmp_path: Path) -> None:
        assert cos_init._remove_stale_os_only_skills(str(tmp_path / "nope"), "", "both") == []

    def test_prunes_dangling_driver_symlink_after_force_wipe(self, tmp_path: Path) -> None:
        """COGNITIVE_OS_FORCE=true wipes .cognitive-os before cos_init runs,
        orphaning .claude/skills symlinks of skills no longer reinstalled."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        kernel.mkdir(parents=True)
        driver.mkdir(parents=True)
        # Dangling cos-namespace symlink (kernel dir was force-wiped).
        (driver / "fake-os-skill").symlink_to("../../.cognitive-os/skills/cos/fake-os-skill")
        # Healthy cos-namespace symlink.
        live = kernel / "compose-prompt"
        live.mkdir()
        (live / "SKILL.md").write_text("---\nname: compose-prompt\n---\n<!-- SCOPE: both -->\n# S\n")
        (driver / "compose-prompt").symlink_to("../../.cognitive-os/skills/cos/compose-prompt")
        # User-managed dangling symlink OUTSIDE the cos namespace — untouched.
        (driver / "my-own").symlink_to("../../somewhere/else")
        cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert not (driver / "fake-os-skill").is_symlink()
        assert (driver / "compose-prompt").is_symlink()
        assert (driver / "my-own").is_symlink()

    # ── B-1: driver projections are removed ONLY when they are COS symlinks ──

    _OS_ONLY_BODY = "---\nname: fake-os-skill\n---\n<!-- SCOPE: os-only -->\n# Skill\n"

    def _seed_stale_kernel_skill(self, kernel: Path, name: str = "fake-os-skill") -> Path:
        skill = kernel / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(self._OS_ONLY_BODY)
        return skill

    def test_real_user_dir_at_driver_path_survives(self, tmp_path: Path) -> None:
        """B-1(a): a REAL directory at .claude/skills/<stale-name> is
        user-authored (COS only ever creates symlinks there) — it survives
        the reinstall sweep while the stale kernel dir is removed."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        stale = self._seed_stale_kernel_skill(kernel)
        user_dir = driver / "fake-os-skill"
        user_dir.mkdir(parents=True)
        (user_dir / "SKILL.md").write_text("# My customized copy\n")
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == ["fake-os-skill"]
        assert not stale.exists()
        assert user_dir.is_dir()
        assert (user_dir / "SKILL.md").read_text() == "# My customized copy\n"

    def test_real_user_file_at_driver_path_survives(self, tmp_path: Path) -> None:
        """B-1(b): a REAL file at the driver path is user content — never deleted."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        stale = self._seed_stale_kernel_skill(kernel)
        driver.mkdir(parents=True)
        user_file = driver / "fake-os-skill"
        user_file.write_text("user notes\n")
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == ["fake-os-skill"]
        assert not stale.exists()
        assert user_file.is_file()
        assert user_file.read_text() == "user notes\n"

    def test_cos_symlink_projection_is_still_removed(self, tmp_path: Path) -> None:
        """B-1(c): the legitimate COS symlink projection is still cleaned up."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        stale = self._seed_stale_kernel_skill(kernel)
        driver.mkdir(parents=True)
        (driver / "fake-os-skill").symlink_to("../../.cognitive-os/skills/cos/fake-os-skill")
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == ["fake-os-skill"]
        assert not stale.exists()
        assert not (driver / "fake-os-skill").is_symlink()
        assert not (driver / "fake-os-skill").exists()

    def test_user_symlink_to_non_cos_target_survives(self, tmp_path: Path) -> None:
        """B-1: a user symlink at the stale name pointing OUTSIDE the cos
        kernel namespace is not unlinked."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        self._seed_stale_kernel_skill(kernel)
        driver.mkdir(parents=True)
        (driver / "fake-os-skill").symlink_to("../../my-skills/fake-os-skill")
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == ["fake-os-skill"]
        assert (driver / "fake-os-skill").is_symlink()

    # ── L-2: dangling prune only touches links into THIS project's kernel ──

    def test_dangling_link_to_other_projects_kernel_survives(self, tmp_path: Path) -> None:
        """L-2: a dangling user link whose target contains the cos namespace
        substring but resolves into ANOTHER project's kernel is never pruned."""
        kernel = tmp_path / "proj" / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / "proj" / ".claude" / "skills"
        kernel.mkdir(parents=True)
        driver.mkdir(parents=True)
        other_target = tmp_path / "other-project" / ".cognitive-os" / "skills" / "cos" / "foo"
        (driver / "foo").symlink_to(str(other_target))  # dangling — never created
        relative_other = "../../../other-project/.cognitive-os/skills/cos/bar"
        (driver / "bar").symlink_to(relative_other)  # dangling, relative, other project
        cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert (driver / "foo").is_symlink()
        assert (driver / "bar").is_symlink()

    def test_dangling_link_to_this_projects_kernel_is_pruned(self, tmp_path: Path) -> None:
        """L-2: a dangling link resolving into THIS project's kernel is pruned."""
        kernel = tmp_path / "proj" / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / "proj" / ".claude" / "skills"
        kernel.mkdir(parents=True)
        driver.mkdir(parents=True)
        (driver / "gone").symlink_to("../../.cognitive-os/skills/cos/gone")
        cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert not (driver / "gone").is_symlink()
        assert not (driver / "gone").exists()

    def test_body_prose_scope_is_not_swept(self, tmp_path: Path) -> None:
        """L-3 x sweep: a marker-less skill with `scope: os` in body prose is
        NOT classified os-only and survives the reinstall sweep."""
        kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
        driver = tmp_path / ".claude" / "skills"
        skill = kernel / "doc-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: doc-skill\n---\n# Skill\n\nExample:\n\nscope: os\n"
        )
        driver.mkdir(parents=True)
        (driver / "doc-skill").symlink_to("../../.cognitive-os/skills/cos/doc-skill")
        removed = cos_init._remove_stale_os_only_skills(str(kernel), str(driver), "both")
        assert removed == []
        assert (skill / "SKILL.md").is_file()
        assert (driver / "doc-skill").is_symlink()


class TestCountInstalledSkills:
    """M-1: skills_installed recount parity with cmd/cos countSkillDirs."""

    def test_counts_only_skill_md_bearing_visible_dirs(self, tmp_path: Path) -> None:
        kernel = tmp_path / "kernel"
        for name in ("alpha", "beta"):
            d = kernel / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("# S\n")
        (kernel / "no-skill-md").mkdir()  # dir without SKILL.md — not counted
        lib_dir = kernel / "_lib"
        lib_dir.mkdir()
        (lib_dir / "SKILL.md").write_text("# S\n")  # underscore prefix — not counted
        hidden = kernel / ".hidden"
        hidden.mkdir()
        (hidden / "SKILL.md").write_text("# S\n")  # dot prefix — not counted
        (kernel / "CATALOG.md").write_text("# Catalog\n")  # plain file — not counted
        assert cos_init._count_installed_skills(str(kernel)) == 2

    def test_missing_root_is_zero(self, tmp_path: Path) -> None:
        assert cos_init._count_installed_skills(str(tmp_path / "nope")) == 0


class TestFilteredSkillsCatalog:
    """Installed CATALOG.md must not advertise scope-filtered skills."""

    def test_os_only_row_dropped_others_kept(self, tmp_path: Path) -> None:
        skills_src = tmp_path / "skills"
        for name, scope in (("cos-status", "os-only"), ("compose-prompt", "both")):
            d = skills_src / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n<!-- SCOPE: {scope} -->\n# S\n")
        catalog = skills_src / "CATALOG.md"
        catalog.write_text(
            "<!-- SCOPE: both -->\n# Catalog\n\n"
            "| Skill | Description |\n|-------|-------------|\n"
            "| cos-status | OS status |\n| compose-prompt | Compose |\n"
            "| retired-skill | No dir on disk |\n"
        )
        out = cos_init._filtered_skills_catalog(catalog, skills_src, "both")
        assert "| cos-status |" not in out
        assert "| compose-prompt |" in out
        assert "| retired-skill |" in out  # no source dir → kept verbatim
        assert "| Skill | Description |" in out  # header kept
        assert "|-------|" in out  # separator kept

    def test_install_scope_all_copies_verbatim(self, tmp_path: Path) -> None:
        skills_src = tmp_path / "skills"
        d = skills_src / "cos-status"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: cos-status\n---\n<!-- SCOPE: os-only -->\n# S\n")
        catalog = skills_src / "CATALOG.md"
        text = "# Catalog\n| cos-status | OS status |\n"
        catalog.write_text(text)
        assert cos_init._filtered_skills_catalog(catalog, skills_src, "all") == text


# ── Template scope filtering (component-scope-classification DoD items 1 + 3) ──

class TestTemplateInstallScopeFilter:
    """Verify scope_allows() correctly filters templates by <!-- SCOPE: ... --> header.

    DoD items from .cognitive-os/plans/features/component-scope-classification.md:
      - Item 1: All 433 components have a scope tag (templates confirmed 2026-04-30)
      - Item 3: cos install (cos_init.py main) skips os-only components

    Templates use <!-- SCOPE: {scope} --> comment on the first line (plan step 4).
    The installer calls scope_allows() for each .md before copying.
    """

    def test_scope_allows_filters_template_os_only(self, tmp_path: Path) -> None:
        """scope_allows() blocks templates tagged '<!-- SCOPE: os-only -->'."""
        tmpl = tmp_path / "project-gotchas.md"
        tmpl.write_text("<!-- SCOPE: os-only -->\n# Project Gotchas\n")
        assert cos_init.scope_allows(str(tmpl), install_scope="both") is False

    def test_scope_allows_passes_template_both(self, tmp_path: Path) -> None:
        """scope_allows() passes templates tagged '<!-- SCOPE: both -->'."""
        tmpl = tmp_path / "quality-gates.md"
        tmpl.write_text("<!-- SCOPE: both -->\n# Quality Gates\n")
        assert cos_init.scope_allows(str(tmpl), install_scope="both") is True

    def test_scope_allows_passes_template_project(self, tmp_path: Path) -> None:
        """scope_allows() passes templates tagged '<!-- SCOPE: project -->'."""
        tmpl = tmp_path / "fintech-gates.md"
        tmpl.write_text("<!-- SCOPE: project -->\n# Fintech Gates\n")
        assert cos_init.scope_allows(str(tmpl), install_scope="both") is True

    def test_real_template_scope_tags_present(self) -> None:
        """All real templates in templates/ must have a '<!-- SCOPE: ...' tag on line 1.

        DoD item 1: every component has a scope tag.
        Templates use '<!-- SCOPE: {scope} -->' on the first line (per plan step 4).
        """
        templates_dir = PROJECT_ROOT / "templates"
        if not templates_dir.is_dir():
            return  # templates/ not present in this environment

        missing = []
        for tmpl in sorted(templates_dir.glob("*.md")):
            try:
                first_line = tmpl.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                first_line = ""
            if "<!-- SCOPE:" not in first_line:
                missing.append(tmpl.name)

        assert not missing, (
            f"Templates lacking '<!-- SCOPE: ...' tag on line 1: {missing}\n"
            f"Add '<!-- SCOPE: both -->' (or os-only/project) as the very first line."
        )

    def test_real_os_only_templates_are_filtered(self) -> None:
        """Templates tagged os-only in the real repo are correctly blocked by scope_allows().

        This verifies the integration between scope tags on disk and scope_allows(),
        ensuring cos_init.py main()'s template install loop actually filters them.
        """
        templates_dir = PROJECT_ROOT / "templates"
        if not templates_dir.is_dir():
            return

        for tmpl in sorted(templates_dir.glob("*.md")):
            try:
                first_line = tmpl.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                continue
            if "<!-- SCOPE: os-only" in first_line:
                assert cos_init.scope_allows(str(tmpl), install_scope="both") is False, (
                    f"Expected {tmpl.name} to be blocked (os-only), but scope_allows returned True"
                )


def test_registry_register_skips_ephemeral_without_explicit_registry(tmp_path, monkeypatch):
    """cos-init must not write tmp/canary installs to the production registry."""
    import scripts.cos_init as cos_init

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "cos-canary-default"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("COS_REGISTRY_FILE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    cos_init._registry_register(
        str(project),
        "default",
        "0.21.0",
        "cos-canary-default",
        str(PROJECT_ROOT),
    )

    assert not (home / ".cognitive-os" / "installations.json").exists()


def test_registry_register_honors_explicit_registry_for_tmp_install(tmp_path, monkeypatch):
    """Test registries can still model tmp installs explicitly."""
    import scripts.cos_init as cos_init

    registry_file = tmp_path / "registry.json"
    project = tmp_path / "cos-canary-default"
    project.mkdir()
    monkeypatch.setenv("COS_REGISTRY_FILE", str(registry_file))
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    cos_init._registry_register(
        str(project),
        "default",
        "0.21.0",
        "cos-canary-default",
        str(PROJECT_ROOT),
    )

    data = json.loads(registry_file.read_text())
    assert data["installations"][0]["project_name"] == "cos-canary-default"



def test_install_provenance_scan_guardrail_copies_project_policy_and_bin(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "manifests").mkdir(parents=True)
    (source / "scripts" / "provenance-scan").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (source / "scripts" / "provenance_scan.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "manifests" / "provenance-scan.yaml").write_text("schema_version: provenance-scan/v1\n", encoding="utf-8")
    project.mkdir()

    assert cos_init._install_provenance_scan_guardrail(project, source) is True

    wrapper = project / ".cognitive-os" / "bin" / "provenance-scan"
    assert wrapper.exists()
    assert wrapper.stat().st_mode & 0o111
    assert (project / ".cognitive-os" / "bin" / "provenance_scan.py").exists()
    assert (project / ".cognitive-os" / "provenance-scan.yaml").read_text(encoding="utf-8").startswith("schema_version")


# ── End-to-end: reinstall sweep never deletes user content (B-1 + M-1) ──

def test_e2e_reinstall_removes_stale_kernel_skill_but_keeps_user_dir(tmp_path: Path) -> None:
    """Full cos-init run over a seeded project (force-reinstall scenario):

    - `.cognitive-os/skills/cos/fake-os-skill/` (os-only marker) → removed
    - REAL user dir `.claude/skills/fake-os-skill/` with a file → intact
    - install-meta skills_installed matches the SKILL.md-bearing dir count (M-1)
    """
    cos_status_default = "cos-status" in cos_init.DEFAULT_SKILLS
    assert cos_status_default is False  # L-1: dead default entry removed

    kernel = tmp_path / ".cognitive-os" / "skills" / "cos"
    stale = kernel / "fake-os-skill"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text(
        "---\nname: fake-os-skill\n---\n<!-- SCOPE: os-only -->\n# Skill\n"
    )
    user_dir = tmp_path / ".claude" / "skills" / "fake-os-skill"
    user_dir.mkdir(parents=True)
    (user_dir / "SKILL.md").write_text("# My customized copy\n")

    env = dict(os.environ)
    env["COGNITIVE_OS_FORCE"] = "true"
    env.pop("COS_INSTALL_SCOPE", None)
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "cos_init.py"), "--default", "--harness", "claude"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    # Stale os-only kernel skill removed by the sweep.
    assert not stale.exists()
    # User-authored real directory at the driver path survives, file intact.
    assert user_dir.is_dir()
    assert (user_dir / "SKILL.md").read_text() == "# My customized copy\n"

    # M-1: reported count uses the cos-status definition (SKILL.md-bearing,
    # non-underscore, non-dot dirs only).
    install_meta = json.loads((tmp_path / ".cognitive-os" / "install-meta.json").read_text())
    expected = sum(
        1
        for p in kernel.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "SKILL.md").is_file()
    )
    assert install_meta["skills_installed"] == expected
    assert expected > 0
