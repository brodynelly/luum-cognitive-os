package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Unit Tests — discoverPackages
// ---------------------------------------------------------------------------

func TestDiscoverPackages_Empty(t *testing.T) {
	dir := t.TempDir()
	// Create packages/ directory but leave it empty.
	if err := os.MkdirAll(filepath.Join(dir, "packages"), 0755); err != nil {
		t.Fatal(err)
	}

	statuses, err := discoverPackages(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(statuses) != 0 {
		t.Errorf("expected 0 statuses, got %d", len(statuses))
	}
}

func TestDiscoverPackages_WithPackages(t *testing.T) {
	dir := t.TempDir()
	packagesDir := filepath.Join(dir, "packages")

	// Create two packages.
	createMinimalPackage(t, packagesDir, "alpha", "@test/alpha", "1.0.0")
	createMinimalPackage(t, packagesDir, "beta", "@test/beta", "2.1.0")

	statuses, err := discoverPackages(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(statuses) != 2 {
		t.Fatalf("expected 2 statuses, got %d", len(statuses))
	}

	// Should be sorted by name.
	if statuses[0].Name != "@test/alpha" {
		t.Errorf("expected first package @test/alpha, got %s", statuses[0].Name)
	}
	if statuses[1].Name != "@test/beta" {
		t.Errorf("expected second package @test/beta, got %s", statuses[1].Name)
	}

	// No git tags exist, so all should be "never released".
	for _, s := range statuses {
		if s.LastTag != "" {
			t.Errorf("expected empty LastTag for %s, got %s", s.Name, s.LastTag)
		}
		if !s.HasChanges {
			t.Errorf("expected HasChanges=true for %s (no tag exists)", s.Name)
		}
	}
}

func TestDiscoverPackages_SkipsInvalidManifests(t *testing.T) {
	dir := t.TempDir()
	packagesDir := filepath.Join(dir, "packages")

	// Create one valid and one invalid package.
	createMinimalPackage(t, packagesDir, "valid", "@test/valid", "1.0.0")
	invalidDir := filepath.Join(packagesDir, "invalid")
	if err := os.MkdirAll(invalidDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(invalidDir, "cos-package.yaml"), []byte("not: valid: yaml: ["), 0644); err != nil {
		t.Fatal(err)
	}

	statuses, err := discoverPackages(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(statuses) != 1 {
		t.Errorf("expected 1 status (skipping invalid), got %d", len(statuses))
	}
}

func TestDiscoverPackages_NoPackagesDir(t *testing.T) {
	dir := t.TempDir()
	// No packages/ directory at all.
	_, err := discoverPackages(dir)
	if err == nil {
		t.Error("expected error when packages/ directory doesn't exist")
	}
}

// ---------------------------------------------------------------------------
// Unit Tests — matchesFilter
// ---------------------------------------------------------------------------

func TestMatchesFilter(t *testing.T) {
	tests := []struct {
		name    string
		include string
		exclude string
		want    bool
	}{
		{"@luum/quality-gates", "", "", true},
		{"@luum/quality-gates", "quality", "", true},
		{"@luum/quality-gates", "trust", "", false},
		{"@luum/quality-gates", "", "quality", false},
		{"@luum/quality-gates", "quality,trust", "", true},
		{"@luum/quality-gates", "", "trust,sdd", true},
		{"@luum/quality-gates", "quality", "quality", false}, // exclude wins
	}

	for _, tt := range tests {
		got := matchesFilter(tt.name, tt.include, tt.exclude)
		if got != tt.want {
			t.Errorf("matchesFilter(%q, %q, %q) = %v, want %v",
				tt.name, tt.include, tt.exclude, got, tt.want)
		}
	}
}

// ---------------------------------------------------------------------------
// E2E Tests — cos status
// ---------------------------------------------------------------------------

func TestE2E_StatusCommand(t *testing.T) {
	dir := setupGitProjectWithPackages(t)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}

	// Header line makes the resolved root visible (M-2).
	if !strings.Contains(out, "Cognitive OS release status — "+dir) {
		t.Errorf("expected resolved-root header line in release output:\n%s", out)
	}

	// Should show both packages.
	if !strings.Contains(out, "@test/alpha") {
		t.Errorf("expected output to contain @test/alpha:\n%s", out)
	}
	if !strings.Contains(out, "@test/beta") {
		t.Errorf("expected output to contain @test/beta:\n%s", out)
	}
}

func TestE2E_StatusJSON(t *testing.T) {
	dir := setupGitProjectWithPackages(t)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir, "--json")
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}

	// Release JSON is an envelope identifying the resolved root (M-2).
	var payload struct {
		ProjectDir string `json:"project_dir"`
		Packages   []struct {
			Name string `json:"name"`
		} `json:"packages"`
	}
	if err := json.Unmarshal([]byte(out), &payload); err != nil {
		t.Fatalf("output is not valid JSON: %v\n%s", err, out)
	}
	if payload.ProjectDir != dir {
		t.Errorf("project_dir = %q, want %q", payload.ProjectDir, dir)
	}
	if len(payload.Packages) != 2 {
		t.Fatalf("expected 2 packages in JSON, got %d:\n%s", len(payload.Packages), out)
	}
	if payload.Packages[0].Name != "@test/alpha" {
		t.Errorf("expected first JSON package @test/alpha, got %s", payload.Packages[0].Name)
	}
}

func TestE2E_StatusChangedOnly_NoChanges(t *testing.T) {
	dir := setupGitProjectWithTaggedPackages(t)

	out, exitCode := runCos(t, dir, "status", "--changed-only")
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}

	// With tagged packages and no changes, should show "No packages with unreleased changes"
	if !strings.Contains(out, "No packages") {
		t.Errorf("expected 'No packages' message, got:\n%s", out)
	}
}

// ---------------------------------------------------------------------------
// E2E Tests — mode dispatch (H-1: evidence-based, not bare packages/ dir)
// ---------------------------------------------------------------------------

// (a) A consumer project with a packages/ directory holding no
// cos-package.yaml manifests (for example a JS monorepo) plus install-meta
// must dispatch to project mode, not release mode.
func TestE2E_StatusDispatch_PackagesDirWithoutManifests_ProjectMode(t *testing.T) {
	dir := setupInstalledProject(t)
	writeTestFileE2E(t, dir, "packages/web/package.json", "{}")

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}
	if !strings.Contains(out, "Cognitive OS project status") {
		t.Errorf("expected project-mode output:\n%s", out)
	}
	if strings.Contains(out, "No packages found") {
		t.Errorf("packages/ dir without manifests must not trigger release mode:\n%s", out)
	}
}

// (b) Manifest evidence (packages/*/cos-package.yaml) dispatches to release
// mode — the existing behavior for the Cognitive OS source repository.
func TestE2E_StatusDispatch_ManifestEvidence_ReleaseMode(t *testing.T) {
	dir := setupGitProjectWithPackages(t)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}
	if !strings.Contains(out, "Cognitive OS release status") {
		t.Errorf("expected release-mode output:\n%s", out)
	}
	if !strings.Contains(out, "@test/alpha") {
		t.Errorf("expected release table to list @test/alpha:\n%s", out)
	}
}

// (c) When BOTH package manifests and install-meta are present (a self-hosted
// Cognitive OS source repo), manifest evidence wins: release mode.
func TestE2E_StatusDispatch_BothPresent_ReleaseMode(t *testing.T) {
	dir := setupGitProjectWithPackages(t)
	writeTestFileE2E(t, dir, ".cognitive-os/install-meta.json",
		`{"mode":"default","version":"0.29.28","harness":"claude","project_name":"self-hosted",`+
			`"rules_installed":1,"hooks_installed":1,"skills_installed":1}`)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}
	if !strings.Contains(out, "Cognitive OS release status") {
		t.Errorf("expected release-mode output when both are present:\n%s", out)
	}
	if strings.Contains(out, "Cognitive OS project status") {
		t.Errorf("manifest evidence must win over install-meta:\n%s", out)
	}
}

// ---------------------------------------------------------------------------
// Unit Tests — project mode
// ---------------------------------------------------------------------------

func TestBuildProjectStatus_Full(t *testing.T) {
	dir := setupInstalledProject(t)

	status, err := buildProjectStatus(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if status.Mode != "project" {
		t.Errorf("Mode = %q, want project", status.Mode)
	}
	if status.Name != "fixture-project" {
		t.Errorf("Name = %q, want fixture-project (from cognitive-os.yaml)", status.Name)
	}
	if status.Version != "0.29.28" {
		t.Errorf("Version = %q, want 0.29.28", status.Version)
	}
	if status.Profile != "default" {
		t.Errorf("Profile = %q, want default", status.Profile)
	}
	if status.Harness != "claude" {
		t.Errorf("Harness = %q, want claude", status.Harness)
	}
	if status.Phase != "stabilization" {
		t.Errorf("Phase = %q, want stabilization", status.Phase)
	}
	if status.Hooks.Installed != 3 || status.Hooks.OnDisk != 2 {
		t.Errorf("Hooks = %+v, want installed=3 on_disk=2 (symlink+target=1, _lib excluded)", status.Hooks)
	}
	if status.Rules.Installed != 2 || status.Rules.OnDisk != 2 {
		t.Errorf("Rules = %+v, want installed=2 on_disk=2", status.Rules)
	}
	if status.Skills.Installed != 1 || status.Skills.OnDisk != 1 {
		t.Errorf("Skills = %+v, want installed=1 on_disk=1 (CATALOG.md not a skill, non-cos namespace excluded)", status.Skills)
	}
	if status.Cosd != "stopped" {
		t.Errorf("Cosd = %q, want stopped (cosd dir exists, no pid)", status.Cosd)
	}
	if !status.Coverage.Present || status.Coverage.Total != 65 || status.Coverage.Wired != 64 ||
		status.Coverage.Partial != 1 || status.Coverage.Missing != 0 {
		t.Errorf("Coverage = %+v, want present total=65 wired=64 partial=1 missing=0", status.Coverage)
	}
	if status.ActiveSessions == nil || *status.ActiveSessions != 2 {
		t.Errorf("ActiveSessions = %v, want 2", status.ActiveSessions)
	}
}

func TestBuildProjectStatus_NameFallsBackToDirName(t *testing.T) {
	dir := setupInstalledProject(t)
	// Remove cognitive-os.yaml: name falls back to dir name, phase is empty.
	if err := os.Remove(filepath.Join(dir, "cognitive-os.yaml")); err != nil {
		t.Fatal(err)
	}

	status, err := buildProjectStatus(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if status.Name != filepath.Base(dir) {
		t.Errorf("Name = %q, want dir base %q", status.Name, filepath.Base(dir))
	}
	if status.Phase != "" {
		t.Errorf("Phase = %q, want empty", status.Phase)
	}
}

func TestBuildProjectStatus_MissingOptionalArtifacts(t *testing.T) {
	dir := t.TempDir()
	writeTestFileE2E(t, dir, ".cognitive-os/install-meta.json",
		`{"mode":"default","version":"1.0.0","harness":"claude","rules_installed":0,"hooks_installed":0,"skills_installed":0}`)

	status, err := buildProjectStatus(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if status.Cosd != "absent" {
		t.Errorf("Cosd = %q, want absent (no cosd dir)", status.Cosd)
	}
	if status.Coverage.Present {
		t.Errorf("Coverage.Present = true, want false")
	}
	if status.ActiveSessions != nil {
		t.Errorf("ActiveSessions = %v, want nil (no ledger)", status.ActiveSessions)
	}
}

func TestCosdState(t *testing.T) {
	// Absent: no cosd dir.
	dir := t.TempDir()
	if got := cosdState(dir); got != "absent" {
		t.Errorf("cosdState(no cosd dir) = %q, want absent", got)
	}

	// Stopped: cosd dir exists, no pid file.
	if err := os.MkdirAll(filepath.Join(dir, ".cognitive-os", "cosd", "runtime"), 0755); err != nil {
		t.Fatal(err)
	}
	if got := cosdState(dir); got != "stopped" {
		t.Errorf("cosdState(no pid file) = %q, want stopped", got)
	}

	// Stopped: pid file with a dead pid.
	pidPath := filepath.Join(dir, ".cognitive-os", "cosd", "runtime", "cosd.pid")
	if err := os.WriteFile(pidPath, []byte("99999999\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if got := cosdState(dir); got != "stopped" {
		t.Errorf("cosdState(dead pid) = %q, want stopped", got)
	}

	// Stopped: garbage pid file.
	if err := os.WriteFile(pidPath, []byte("not-a-pid\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if got := cosdState(dir); got != "stopped" {
		t.Errorf("cosdState(garbage pid) = %q, want stopped", got)
	}

	// Running: pid file pointing at this test process (signal 0 succeeds).
	if err := os.WriteFile(pidPath, []byte(fmt.Sprintf("%d\n", os.Getpid())), 0644); err != nil {
		t.Fatal(err)
	}
	if got := cosdState(dir); got != "running" {
		t.Errorf("cosdState(live pid) = %q, want running", got)
	}
}

// ---------------------------------------------------------------------------
// E2E Tests — cos status (project mode + neither mode)
// ---------------------------------------------------------------------------

func TestE2E_StatusProjectMode(t *testing.T) {
	dir := setupInstalledProject(t)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}

	for _, want := range []string{
		"Cognitive OS project status",
		"fixture-project",
		"0.29.28",
		"claude",
		"stabilization",
		"3 (2 on disk)", // hooks drift visible
		"2 (2 on disk)", // rules
		"1 (1 on disk)", // skills
		"stopped",
		"65 total",
		"2 active",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("expected output to contain %q:\n%s", want, out)
		}
	}
}

func TestE2E_StatusProjectModeJSON(t *testing.T) {
	dir := setupInstalledProject(t)

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir, "--json")
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d. Output:\n%s", exitCode, out)
	}

	var payload struct {
		Mode    string `json:"mode"`
		Name    string `json:"name"`
		Version string `json:"version"`
		Harness string `json:"harness"`
		Phase   string `json:"phase"`
		Hooks   struct {
			Installed int `json:"installed"`
			OnDisk    int `json:"on_disk"`
		} `json:"hooks"`
		Cosd     string `json:"cosd"`
		Coverage struct {
			Present bool `json:"present"`
			Total   int  `json:"total"`
		} `json:"coverage"`
		ActiveSessions *int `json:"active_sessions"`
	}
	if err := json.Unmarshal([]byte(out), &payload); err != nil {
		t.Fatalf("output is not valid JSON: %v\n%s", err, out)
	}
	if payload.Mode != "project" || payload.Name != "fixture-project" ||
		payload.Version != "0.29.28" || payload.Harness != "claude" || payload.Phase != "stabilization" {
		t.Errorf("unexpected JSON identity fields: %+v", payload)
	}
	if payload.Hooks.Installed != 3 || payload.Hooks.OnDisk != 2 {
		t.Errorf("hooks = %+v, want installed=3 on_disk=2", payload.Hooks)
	}
	if payload.Cosd != "stopped" {
		t.Errorf("cosd = %q, want stopped", payload.Cosd)
	}
	if !payload.Coverage.Present || payload.Coverage.Total != 65 {
		t.Errorf("coverage = %+v, want present total=65", payload.Coverage)
	}
	if payload.ActiveSessions == nil || *payload.ActiveSessions != 2 {
		t.Errorf("active_sessions = %v, want 2", payload.ActiveSessions)
	}
}

func TestE2E_StatusNeitherMode(t *testing.T) {
	dir := t.TempDir()

	out, exitCode := runCos(t, dir, "status", "--project-dir", dir)
	if exitCode == 0 {
		t.Fatalf("expected non-zero exit, got 0. Output:\n%s", out)
	}
	for _, want := range []string{"release mode", "project mode", "packages", "install-meta.json"} {
		if !strings.Contains(out, want) {
			t.Errorf("expected error output to contain %q:\n%s", want, out)
		}
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// setupInstalledProject creates a temp directory that looks like a consumer
// project with Cognitive OS installed (project mode: install-meta.json
// present, no packages/ directory).
func setupInstalledProject(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()

	writeTestFileE2E(t, dir, "cognitive-os.yaml",
		"project:\n  name: fixture-project\n  phase: stabilization\n")
	writeTestFileE2E(t, dir, ".cognitive-os/install-meta.json",
		`{"mode":"default","version":"0.29.28","harness":"claude","project_name":"workspace",`+
			`"rules_installed":2,"hooks_installed":3,"skills_installed":1}`)

	// Hooks: two real files, one symlink to an existing hook (counts once),
	// and a _lib helper dir that must be excluded.
	writeTestFileE2E(t, dir, ".cognitive-os/hooks/cos/alpha.sh", "#!/bin/sh\n")
	writeTestFileE2E(t, dir, ".cognitive-os/hooks/cos/beta.sh", "#!/bin/sh\n")
	writeTestFileE2E(t, dir, ".cognitive-os/hooks/cos/_lib/helper.sh", "#!/bin/sh\n")
	if err := os.Symlink(
		filepath.Join(dir, ".cognitive-os", "hooks", "cos", "alpha.sh"),
		filepath.Join(dir, ".cognitive-os", "hooks", "alpha-link.sh"),
	); err != nil {
		t.Fatal(err)
	}

	// Rules: two markdown files.
	writeTestFileE2E(t, dir, ".cognitive-os/rules/cos/one.md", "# one\n")
	writeTestFileE2E(t, dir, ".cognitive-os/rules/cos/two.md", "# two\n")

	// Skills: one skill dir with SKILL.md plus a loose CATALOG.md (not a
	// skill). A skill in a non-cos namespace must NOT count: the on-disk
	// count is restricted to the cos/ kernel namespace to match
	// install-meta's skills_installed definition (M-1).
	writeTestFileE2E(t, dir, ".cognitive-os/skills/cos/sample/SKILL.md", "# sample\n")
	writeTestFileE2E(t, dir, ".cognitive-os/skills/cos/CATALOG.md", "# catalog\n")
	writeTestFileE2E(t, dir, ".cognitive-os/skills/tac/extra/SKILL.md", "# extra\n")

	// cosd runtime dir without a pid file: stopped.
	if err := os.MkdirAll(filepath.Join(dir, ".cognitive-os", "cosd", "runtime"), 0755); err != nil {
		t.Fatal(err)
	}

	// Coverage artifact (cos-project-coverage.v1) and session ledger.
	writeTestFileE2E(t, dir, ".cognitive-os/reports/coverage-latest.json",
		`{"schema_version":"cos-project-coverage.v1","summary":{"total":65,"wired":64,"partial":1,"missing":0}}`)
	writeTestFileE2E(t, dir, ".cognitive-os/sessions/active-sessions.json",
		`{"sessions":[{"id":"a"},{"id":"b"}]}`)

	return dir
}

func createMinimalPackage(t *testing.T, packagesDir, dirName, name, version string) {
	t.Helper()
	pkgDir := filepath.Join(packagesDir, dirName)
	if err := os.MkdirAll(pkgDir, 0755); err != nil {
		t.Fatal(err)
	}
	content := "name: \"" + name + "\"\nversion: \"" + version + "\"\ndescription: \"Test\"\nlicense: \"MIT\"\nexports: []\n"
	if err := os.WriteFile(filepath.Join(pkgDir, "cos-package.yaml"), []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
}

func setupGitProjectWithPackages(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()

	// Initialize git.
	gitInit := exec.Command("git", "init")
	gitInit.Dir = dir
	if out, err := gitInit.CombinedOutput(); err != nil {
		t.Fatalf("git init: %v\n%s", err, out)
	}

	// Configure git user for commits.
	for _, cfg := range [][]string{
		{"config", "user.email", "test@test.com"},
		{"config", "user.name", "Test"},
	} {
		cmd := exec.Command("git", cfg...)
		cmd.Dir = dir
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git config: %v\n%s", err, out)
		}
	}

	// Create project markers.
	writeTestFileE2E(t, dir, "cognitive-os.yaml", "project:\n  name: test\n")
	writeTestFileE2E(t, dir, "VERSION", "0.1.0\n")

	// Create packages.
	createMinimalPackage(t, filepath.Join(dir, "packages"), "alpha", "@test/alpha", "1.0.0")
	createMinimalPackage(t, filepath.Join(dir, "packages"), "beta", "@test/beta", "1.0.0")

	// Initial commit.
	gitAdd := exec.Command("git", "add", "-A")
	gitAdd.Dir = dir
	if out, err := gitAdd.CombinedOutput(); err != nil {
		t.Fatalf("git add: %v\n%s", err, out)
	}
	gitCommit := exec.Command("git", "commit", "-m", "init")
	gitCommit.Dir = dir
	if out, err := gitCommit.CombinedOutput(); err != nil {
		t.Fatalf("git commit: %v\n%s", err, out)
	}

	return dir
}

func setupGitProjectWithTaggedPackages(t *testing.T) string {
	t.Helper()
	dir := setupGitProjectWithPackages(t)

	// Tag both packages.
	for _, tag := range []string{"@test/alpha@1.0.0", "@test/beta@1.0.0"} {
		gitTag := exec.Command("git", "tag", tag)
		gitTag.Dir = dir
		if out, err := gitTag.CombinedOutput(); err != nil {
			t.Fatalf("git tag %s: %v\n%s", tag, err, out)
		}
	}

	return dir
}
