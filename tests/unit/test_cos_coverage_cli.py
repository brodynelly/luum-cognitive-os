"""Tests for scripts/cos_coverage.py — ACC CLI.

Covers:
  - JSON output schema
  - empty-history fallback (no coverage-history.jsonl)
  - trend calculation when history exists
  - --brief output format
  - cos-project-coverage.v1 artifact (mode detection, schema, symlink counting)
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "cos_coverage.py"

sys.path.insert(0, str(SCRIPT.parent))
import cos_coverage  # noqa: E402


def run_coverage(project_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-dir", str(project_dir), *args],
        capture_output=True,
        text=True,
    )


def make_audit_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def make_claim_proof_md(path: Path, mapped: int, weak: int, unmapped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(f"""
        # Claim-to-Proof Audit — Latest

        ## Summary

        - mapped: {mapped}
        - weak-proof: {weak}
        - unmapped: {unmapped}
        """)
    )


def audit_record(component: str, classification: str) -> dict:
    return {
        "source": "aspirational-audit",
        "event_type": "component.classified",
        "schema_version": "1.0",
        "timestamp": "2026-05-02T12:00:00+00:00",
        "payload": {
            "component": component,
            "classification": classification,
            "signals": {},
            "reason": "test",
        },
    }


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    """Minimal fake project with aspirational-audit.jsonl and claim-proof md."""
    metrics = tmp_path / ".cognitive-os" / "metrics"
    metrics.mkdir(parents=True, exist_ok=True)

    records = [
        audit_record("scripts/real_script.py", "REAL"),
        audit_record("scripts/real_script2.py", "REAL"),
        audit_record("hooks/dormant_hook.sh", "DORMANT"),
        audit_record("scripts/aspirational.py", "ASPIRATIONAL"),
    ]
    make_audit_jsonl(metrics / "aspirational-audit.jsonl", records)
    make_claim_proof_md(
        tmp_path / "docs" / "06-Daily" / "reports" / "claim-proof-latest.md",
        mapped=10, weak=2, unmapped=1,
    )
    return tmp_path


# ── JSON output schema ─────────────────────────────────────────────────────────

class TestJsonOutput:
    def test_json_flag_produces_valid_json(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_json_schema_required_keys(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        for key in ("coverage_pct", "real", "dormant", "aspirational",
                    "mapped", "weak_proof", "unmapped", "trend", "generated_at"):
            assert key in data, f"Missing key: {key}"

    def test_json_coverage_pct_type(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert isinstance(data["coverage_pct"], (int, float))

    def test_json_real_dormant_aspirational_counts(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert data["real"] == 2
        assert data["dormant"] == 1
        assert data["aspirational"] == 1

    def test_json_coverage_pct_calculation(self, fake_project: Path) -> None:
        # REAL=2, DORMANT=1, ASPIRATIONAL=1 -> 2/4 = 50.0%
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert data["coverage_pct"] == 50.0

    def test_json_claim_proof_keys(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert data["mapped"] == 10
        assert data["weak_proof"] == 2
        assert data["unmapped"] == 1

    def test_json_no_internal_cache_key(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert "_cached_at" not in data

    def test_json_trend_is_dict(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert isinstance(data["trend"], dict)

    def test_json_tiers_is_dict(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert isinstance(data.get("tiers", {}), dict)


# ── Empty history fallback ─────────────────────────────────────────────────────

class TestEmptyHistoryFallback:
    def test_no_history_file_exits_ok(self, fake_project: Path) -> None:
        history = fake_project / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
        assert not history.exists()
        result = run_coverage(fake_project, "--json")
        assert result.returncode == 0

    def test_no_history_trend_is_empty(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--json")
        data = json.loads(result.stdout)
        assert data["trend"] == {}

    def test_no_audit_file_exits_ok(self, tmp_path: Path) -> None:
        # No aspirational-audit.jsonl at all
        make_claim_proof_md(
            tmp_path / "docs" / "06-Daily" / "reports" / "claim-proof-latest.md",
            mapped=0, weak=0, unmapped=0,
        )
        result = run_coverage(tmp_path, "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["coverage_pct"] == 0.0
        assert data["real"] == 0
        assert data["dormant"] == 0

    def test_no_claim_proof_exits_ok(self, tmp_path: Path) -> None:
        # Only audit file, no claim-proof md
        metrics = tmp_path / ".cognitive-os" / "metrics"
        metrics.mkdir(parents=True, exist_ok=True)
        make_audit_jsonl(
            metrics / "aspirational-audit.jsonl",
            [audit_record("scripts/foo.py", "REAL")],
        )
        result = run_coverage(tmp_path, "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mapped"] == 0
        assert data["unmapped"] == 0

    def test_empty_project_dir_all_zeros(self, tmp_path: Path) -> None:
        result = run_coverage(tmp_path, "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["coverage_pct"] == 0.0


# ── Trend calculation ──────────────────────────────────────────────────────────

class TestTrendCalculation:
    def _write_history(self, project_dir: Path, snapshots: list[dict]) -> None:
        history = project_dir / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        # Use different dates so they're all written
        with history.open("w") as fh:
            for i, snap in enumerate(snapshots):
                entry = {
                    "timestamp": f"2026-04-{20+i:02d}T12:00:00Z",
                    "source": "cos-coverage",
                    "event_type": "acc_snapshot",
                    "payload": snap,
                }
                fh.write(json.dumps(entry) + "\n")

    def test_trend_up_when_coverage_increased(self, fake_project: Path) -> None:
        # Fake history with lower coverage_pct
        self._write_history(fake_project, [
            {"coverage_pct": 30.0, "real": 1, "dormant": 2, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # Current coverage_pct=50.0 > 30.0 -> up
        assert data["trend"].get("coverage_pct") == "up"

    def test_trend_down_when_coverage_decreased(self, fake_project: Path) -> None:
        self._write_history(fake_project, [
            {"coverage_pct": 80.0, "real": 10, "dormant": 1, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # Current coverage_pct=50.0 < 80.0 -> down
        assert data["trend"].get("coverage_pct") == "down"

    def test_trend_flat_when_unchanged(self, fake_project: Path) -> None:
        self._write_history(fake_project, [
            {"coverage_pct": 50.0, "real": 2, "dormant": 1, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        assert data["trend"].get("coverage_pct") == "flat"

    def test_trend_uses_last_snapshot_not_first(self, fake_project: Path) -> None:
        # Write two snapshots: first says 90% (old), second says 40% (more recent)
        self._write_history(fake_project, [
            {"coverage_pct": 90.0, "real": 9, "dormant": 1, "aspirational": 0},
            {"coverage_pct": 40.0, "real": 4, "dormant": 5, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # Current 50.0 vs last 40.0 -> up
        assert data["trend"].get("coverage_pct") == "up"

    def test_trend_real_up_when_real_count_grew(self, fake_project: Path) -> None:
        self._write_history(fake_project, [
            {"coverage_pct": 50.0, "real": 1, "dormant": 1, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # real=2 now > 1 before
        assert data["trend"].get("real") == "up"

    def test_trend_dormant_up_when_dormant_grew(self, fake_project: Path) -> None:
        self._write_history(fake_project, [
            {"coverage_pct": 50.0, "real": 2, "dormant": 0, "aspirational": 1},
        ])
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # dormant=1 now > 0 before
        assert data["trend"].get("dormant") == "up"

    def test_accepts_legacy_coverage_measurement_events(self, fake_project: Path) -> None:
        """History from pre-existing pre-commit-gate format should also influence trend."""
        history = fake_project / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": "2026-04-15T12:00:00Z",
            "source": "pre-commit-gate",
            "event_type": "coverage_measurement",
            "payload": {"coverage_pct": 25, "commit_sha": "abc", "threshold": 80},
        }
        history.write_text(json.dumps(entry) + "\n")
        result = run_coverage(fake_project, "--json", "--refresh")
        data = json.loads(result.stdout)
        # coverage_pct=50.0 > 25 -> up
        assert data["trend"].get("coverage_pct") == "up"


# ── --brief output format ──────────────────────────────────────────────────────

class TestBriefFormat:
    def test_brief_output_is_single_line(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--brief")
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_brief_contains_acc_prefix(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--brief")
        assert "ACC:" in result.stdout

    def test_brief_contains_real_count(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--brief")
        assert "REAL:" in result.stdout

    def test_brief_contains_dormant_count(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--brief")
        assert "DORM:" in result.stdout

    def test_brief_contains_percentage(self, fake_project: Path) -> None:
        result = run_coverage(fake_project, "--brief")
        assert "%" in result.stdout

    def test_brief_values_match_json(self, fake_project: Path) -> None:
        brief = run_coverage(fake_project, "--brief", "--refresh")
        js = run_coverage(fake_project, "--json")
        data = json.loads(js.stdout)
        pct = str(data["coverage_pct"])
        real = str(data["real"])
        assert pct in brief.stdout
        assert real in brief.stdout

    def test_brief_with_no_data_shows_zero(self, tmp_path: Path) -> None:
        result = run_coverage(tmp_path, "--brief")
        assert result.returncode == 0
        assert "ACC:" in result.stdout

    def test_brief_with_trend_shows_arrow(self, fake_project: Path) -> None:
        history = fake_project / ".cognitive-os" / "metrics" / "coverage-history.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": "2026-04-20T12:00:00Z",
            "source": "cos-coverage",
            "event_type": "acc_snapshot",
            "payload": {"coverage_pct": 10.0, "real": 1, "dormant": 8, "aspirational": 1},
        }
        history.write_text(json.dumps(entry) + "\n")
        result = run_coverage(fake_project, "--brief", "--refresh")
        # 50.0% > 10.0% -> should show ↑
        assert "↑" in result.stdout


# ── Cache behavior ─────────────────────────────────────────────────────────────

class TestCache:
    def test_cache_written_after_first_run(self, fake_project: Path) -> None:
        run_coverage(fake_project, "--refresh")
        cache = fake_project / ".cognitive-os" / "runtime" / "coverage-snapshot.json"
        assert cache.exists()

    def test_cache_contains_cached_at(self, fake_project: Path) -> None:
        run_coverage(fake_project, "--refresh")
        cache = fake_project / ".cognitive-os" / "runtime" / "coverage-snapshot.json"
        data = json.loads(cache.read_text())
        assert "_cached_at" in data
        assert isinstance(data["_cached_at"], (int, float))

    def test_refresh_flag_updates_cache(self, fake_project: Path) -> None:
        run_coverage(fake_project)
        cache = fake_project / ".cognitive-os" / "runtime" / "coverage-snapshot.json"
        first_ts = json.loads(cache.read_text())["_cached_at"]
        # Small sleep to ensure timestamp differs
        time.sleep(0.05)
        run_coverage(fake_project, "--refresh")
        second_ts = json.loads(cache.read_text())["_cached_at"]
        assert second_ts >= first_ts


# ── cos-project-coverage.v1 artifact ───────────────────────────────────────────

ARTIFACT_REL = Path(".cognitive-os") / "reports" / "coverage-latest.json"


def make_installed_project(
    tmp_path: Path,
    *,
    hooks: int = 3,
    rules: int = 2,
    skills: int = 1,
    meta: dict | None = None,
) -> Path:
    """Build a fake INSTALLED project (install-meta + nested component dirs)."""
    cos = tmp_path / ".cognitive-os"
    if meta is None:
        meta = {
            "hooks_installed": hooks,
            "rules_installed": rules,
            "skills_installed": skills,
        }
    cos.mkdir(parents=True, exist_ok=True)
    (cos / "install-meta.json").write_text(json.dumps(meta))

    hooks_dir = cos / "hooks" / "cos"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for i in range(hooks):
        (hooks_dir / f"hook-{i}.sh").write_text("#!/bin/bash\nexit 0\n")
    # Non-component noise: _lib dir and a non-.sh file must not be counted.
    (hooks_dir / "_lib").mkdir(exist_ok=True)
    (hooks_dir / "_lib" / "shared.sh").write_text("# lib\n")
    (hooks_dir / "README.txt").write_text("not a hook\n")

    rules_dir = cos / "rules" / "cos"
    rules_dir.mkdir(parents=True, exist_ok=True)
    for i in range(rules):
        (rules_dir / f"rule-{i}.md").write_text("# rule\n")

    skills_dir = cos / "skills" / "cos"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for i in range(skills):
        skill = skills_dir / f"skill-{i}"
        skill.mkdir(exist_ok=True)
        (skill / "SKILL.md").write_text("# skill\n")
    # CATALOG.md is an index file, not a skill component.
    (skills_dir / "CATALOG.md").write_text("# catalog\n")
    return tmp_path


def read_artifact(project_dir: Path) -> dict:
    return json.loads((project_dir / ARTIFACT_REL).read_text())


class TestModeDetection:
    def test_project_mode_when_install_meta_and_no_acc_inputs(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        assert cos_coverage.detect_mode(tmp_path) == "project"

    def test_source_repo_mode_without_install_meta(self, tmp_path: Path) -> None:
        assert cos_coverage.detect_mode(tmp_path) == "source-repo"

    def test_source_repo_mode_when_acc_inputs_present(self, tmp_path: Path) -> None:
        # install-meta exists, but the project also has ACC source inputs.
        make_installed_project(tmp_path)
        audit = tmp_path / ".cognitive-os" / "metrics" / "aspirational-audit.jsonl"
        make_audit_jsonl(audit, [audit_record("scripts/x.py", "REAL")])
        assert cos_coverage.detect_mode(tmp_path) == "source-repo"

    def test_fake_acc_project_is_source_repo(self, fake_project: Path) -> None:
        assert cos_coverage.detect_mode(fake_project) == "source-repo"


class TestArtifactSchema:
    def test_artifact_written_on_refresh(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        result = run_coverage(tmp_path, "--json", "--refresh")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / ARTIFACT_REL).exists()

    def test_artifact_written_on_cache_miss_without_refresh(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        result = run_coverage(tmp_path, "--json")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / ARTIFACT_REL).exists()

    def test_artifact_top_level_schema(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        run_coverage(tmp_path, "--refresh")
        artifact = read_artifact(tmp_path)
        assert artifact["schema_version"] == "cos-project-coverage.v1"
        assert artifact["mode"] in ("project", "source-repo")
        assert artifact["surfaces"] == ["hooks", "rules", "skills"]
        for key in ("generated_at", "summary", "components"):
            assert key in artifact, f"Missing key: {key}"

    def test_artifact_summary_shape(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        run_coverage(tmp_path, "--refresh")
        summary = read_artifact(tmp_path)["summary"]
        for key in ("total", "wired", "partial", "missing"):
            assert isinstance(summary[key], int), f"summary.{key} not int"

    def test_artifact_components_shape(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        run_coverage(tmp_path, "--refresh")
        components = read_artifact(tmp_path)["components"]
        for surface in ("hooks", "rules", "skills"):
            assert isinstance(components[surface]["installed"], int)

    def test_artifact_generated_at_iso8601_utc(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        run_coverage(tmp_path, "--refresh")
        generated_at = read_artifact(tmp_path)["generated_at"]
        time.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")  # raises if malformed

    def test_artifact_is_valid_json_file(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path)
        run_coverage(tmp_path, "--refresh")
        # No leftover tmp files from the atomic write.
        leftovers = list((tmp_path / ".cognitive-os" / "reports").glob("*.tmp.*"))
        assert leftovers == []

    def test_source_repo_artifact_maps_acc_counts(self, fake_project: Path) -> None:
        # fake_project: REAL=2, DORMANT=1, ASPIRATIONAL=1
        result = run_coverage(fake_project, "--json", "--refresh")
        assert result.returncode == 0, result.stderr
        artifact = read_artifact(fake_project)
        assert artifact["mode"] == "source-repo"
        assert artifact["summary"] == {
            "total": 4, "wired": 2, "partial": 1, "missing": 1,
        }


class TestProjectModeCounts:
    def test_components_count_actual_entries(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path, hooks=5, rules=3, skills=2)
        run_coverage(tmp_path, "--refresh")
        artifact = read_artifact(tmp_path)
        assert artifact["mode"] == "project"
        assert artifact["components"]["hooks"]["installed"] == 5
        assert artifact["components"]["rules"]["installed"] == 3
        assert artifact["components"]["skills"]["installed"] == 2

    def test_summary_total_from_install_meta(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path, hooks=2, rules=2, skills=1)
        run_coverage(tmp_path, "--refresh")
        summary = read_artifact(tmp_path)["summary"]
        assert summary == {"total": 5, "wired": 5, "partial": 0, "missing": 0}

    def test_missing_when_fewer_installed_than_expected(self, tmp_path: Path) -> None:
        # install-meta claims 4 hooks but only 2 are on disk.
        make_installed_project(
            tmp_path, hooks=2, rules=1, skills=1,
            meta={"hooks_installed": 4, "rules_installed": 1, "skills_installed": 1},
        )
        run_coverage(tmp_path, "--refresh")
        summary = read_artifact(tmp_path)["summary"]
        assert summary["total"] == 6
        assert summary["wired"] == 4
        assert summary["missing"] == 2
        assert summary["partial"] == 0

    def test_wired_capped_at_total(self, tmp_path: Path) -> None:
        # More on disk than install-meta claims: wired must not exceed total.
        make_installed_project(
            tmp_path, hooks=5, rules=1, skills=1,
            meta={"hooks_installed": 1, "rules_installed": 1, "skills_installed": 1},
        )
        run_coverage(tmp_path, "--refresh")
        summary = read_artifact(tmp_path)["summary"]
        assert summary["total"] == 3
        assert summary["wired"] == 3
        assert summary["missing"] == 0

    def test_install_meta_without_counts_uses_actual(self, tmp_path: Path) -> None:
        make_installed_project(
            tmp_path, hooks=3, rules=2, skills=1, meta={"version": "1.0.0"},
        )
        run_coverage(tmp_path, "--refresh")
        summary = read_artifact(tmp_path)["summary"]
        assert summary == {"total": 6, "wired": 6, "partial": 0, "missing": 0}

    def test_absent_component_dirs_count_zero(self, tmp_path: Path) -> None:
        cos = tmp_path / ".cognitive-os"
        cos.mkdir(parents=True)
        (cos / "install-meta.json").write_text("{}")
        result = run_coverage(tmp_path, "--json", "--refresh")
        assert result.returncode == 0, result.stderr
        artifact = read_artifact(tmp_path)
        assert artifact["mode"] == "project"
        for surface in ("hooks", "rules", "skills"):
            assert artifact["components"][surface]["installed"] == 0
        assert artifact["summary"] == {
            "total": 0, "wired": 0, "partial": 0, "missing": 0,
        }

    def test_underscore_and_non_component_files_excluded(self, tmp_path: Path) -> None:
        # make_installed_project plants _lib/shared.sh, README.txt, CATALOG.md.
        make_installed_project(tmp_path, hooks=2, rules=1, skills=1)
        run_coverage(tmp_path, "--refresh")
        components = read_artifact(tmp_path)["components"]
        assert components["hooks"]["installed"] == 2
        assert components["skills"]["installed"] == 1


class TestSymlinkCounting:
    def test_symlink_and_target_count_once(self, tmp_path: Path) -> None:
        make_installed_project(tmp_path, hooks=2, rules=1, skills=1)
        hooks_dir = tmp_path / ".cognitive-os" / "hooks" / "cos"
        # Symlink alias to an existing hook inside the same tree.
        (hooks_dir / "alias-hook.sh").symlink_to(hooks_dir / "hook-0.sh")
        assert cos_coverage.count_hook_components(
            tmp_path / ".cognitive-os" / "hooks") == 2

    def test_symlink_to_outside_target_counts_once(self, tmp_path: Path) -> None:
        # Mirrors source-repo layout: hooks/x.sh -> ../packages/.../x.sh
        external = tmp_path / "packages" / "pack" / "hooks"
        external.mkdir(parents=True)
        (external / "external-hook.sh").write_text("#!/bin/bash\n")
        hooks_root = tmp_path / "hooks"
        hooks_root.mkdir()
        (hooks_root / "local-hook.sh").write_text("#!/bin/bash\n")
        (hooks_root / "external-hook.sh").symlink_to(external / "external-hook.sh")
        assert cos_coverage.count_hook_components(hooks_root) == 2

    def test_symlinked_skill_dir_counts_once(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        real_skill = skills_root / "real-skill"
        real_skill.mkdir(parents=True)
        (real_skill / "SKILL.md").write_text("# skill\n")
        (skills_root / "alias-skill").symlink_to(real_skill)
        assert cos_coverage.count_skill_components(skills_root) == 1

    def test_dangling_symlink_not_counted(self, tmp_path: Path) -> None:
        hooks_root = tmp_path / "hooks"
        hooks_root.mkdir()
        (hooks_root / "real.sh").write_text("#!/bin/bash\n")
        (hooks_root / "broken.sh").symlink_to(hooks_root / "gone.sh")
        assert cos_coverage.count_hook_components(hooks_root) == 1

    def test_symlink_loop_does_not_hang(self, tmp_path: Path) -> None:
        hooks_root = tmp_path / "hooks"
        nested = hooks_root / "nested"
        nested.mkdir(parents=True)
        (nested / "deep-hook.sh").write_text("#!/bin/bash\n")
        (nested / "loop").symlink_to(hooks_root)
        assert cos_coverage.count_hook_components(hooks_root) == 1

    def test_rule_symlinks_deduplicated(self, tmp_path: Path) -> None:
        rules_root = tmp_path / "rules"
        rules_root.mkdir()
        (rules_root / "a.md").write_text("# a\n")
        (rules_root / "b.md").symlink_to(rules_root / "a.md")
        assert cos_coverage.count_rule_components(rules_root) == 1
