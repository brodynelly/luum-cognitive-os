package tui

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// isolateResolver pins the resolver's ambient inputs (COS_SOURCE_DIR and the
// installation registry) so tests are deterministic on developer machines.
func isolateResolver(t *testing.T, registryPath string) {
	t.Helper()
	t.Setenv("COS_SOURCE_DIR", "")
	previous := installationsRegistryPath
	installationsRegistryPath = func() string { return registryPath }
	t.Cleanup(func() { installationsRegistryPath = previous })
}

func writeRegistry(t *testing.T, dir, projectPath, sourcePath string) string {
	t.Helper()
	path := filepath.Join(dir, "installations.json")
	payload := `{"installations":[{"path":"` + projectPath + `","source":"` + sourcePath + `"}]}`
	if err := os.WriteFile(path, []byte(payload), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestResolveScriptPrefersRootLocalScripts(t *testing.T) {
	root := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))
	fakeExecutable(t, root, "scripts/cos-coverage", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(root, "cos-coverage")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(root, "scripts", "cos-coverage"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}
}

func TestResolveScriptFallsBackToProjectBin(t *testing.T) {
	root := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))
	fakeExecutable(t, root, ".cognitive-os/bin/cosd", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(root, "cosd")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(root, ".cognitive-os", "bin", "cosd"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}
}

func TestResolveScriptUsesCOSSourceDirEnv(t *testing.T) {
	root := t.TempDir()
	source := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))
	t.Setenv("COS_SOURCE_DIR", source)
	fakeExecutable(t, source, "scripts/cosd", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(root, "cosd")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cosd"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}
}

func TestResolveScriptUsesInstallationRegistrySource(t *testing.T) {
	root := t.TempDir()
	source := t.TempDir()
	registry := writeRegistry(t, t.TempDir(), root, source)
	isolateResolver(t, registry)
	fakeExecutable(t, source, "scripts/cos-coverage", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(root, "cos-coverage")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cos-coverage"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}
}

func TestResolveScriptIgnoresNonExecutableCandidates(t *testing.T) {
	root := t.TempDir()
	source := t.TempDir()
	registry := writeRegistry(t, t.TempDir(), root, source)
	isolateResolver(t, registry)
	// Root-local copy exists but is not executable; registry copy is.
	nonExec := filepath.Join(root, "scripts", "cosd")
	if err := os.MkdirAll(filepath.Dir(nonExec), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(nonExec, []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}
	fakeExecutable(t, source, "scripts/cosd", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(root, "cosd")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cosd"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}
}

func TestRunActionRejectsWhenScriptUnresolvable(t *testing.T) {
	root := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))

	result := RunAction(root, "refresh-coverage", ActionOptions{Confirm: true})
	if result.OK || result.Outcome != "rejected" {
		t.Fatalf("unexpected result for unresolvable script: %#v", result)
	}
	if !strings.Contains(result.Reason, filepath.Join(root, "scripts", "cos-coverage")) {
		t.Fatalf("reason does not list root-local candidate: %q", result.Reason)
	}
	if !strings.Contains(result.Reason, filepath.Join(root, ".cognitive-os", "bin", "cos-coverage")) {
		t.Fatalf("reason does not list project-bin candidate: %q", result.Reason)
	}
	if len(result.Details) != 0 {
		t.Fatalf("unresolvable script must never be executed: %#v", result.Details)
	}
}

func TestCosdSubmitIntentValidationAndCommand(t *testing.T) {
	root := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))
	fakeExecutable(t, root, "scripts/cosd", "#!/usr/bin/env bash\necho '{\"ok\":true}'\n")

	missingNote := RunAction(root, "cosd-submit-intent", ActionOptions{Confirm: true})
	if missingNote.OK || missingNote.Outcome != "rejected" || !strings.Contains(missingNote.Reason, "--intent-note") {
		t.Fatalf("unexpected missing-note result: %#v", missingNote)
	}

	result := RunAction(root, "cosd-submit-intent", ActionOptions{Confirm: true, IntentNote: "pause batch work"})
	if !result.OK || result.Outcome != "success" {
		t.Fatalf("unexpected submit-intent result: %#v", result)
	}
	if len(result.Commands) != 1 {
		t.Fatalf("expected one command, got %#v", result.Commands)
	}
	command := strings.Join(result.Commands[0], " ")
	if !strings.Contains(command, "submit-intent") || !strings.Contains(command, "--kind=operator-request") || !strings.Contains(command, "--note=pause batch work") {
		t.Fatalf("unexpected submit-intent command: %q", command)
	}
}

func TestCosdSubmitIntentRejectsDisallowedKinds(t *testing.T) {
	root := t.TempDir()
	isolateResolver(t, filepath.Join(t.TempDir(), "missing-registry.json"))
	fakeExecutable(t, root, "scripts/cosd", "#!/usr/bin/env bash\necho '{\"ok\":true}'\n")

	for _, kind := range []string{"adr-number-request", "adr-tombstone-request", "anything-else"} {
		result := RunAction(root, "cosd-submit-intent", ActionOptions{Confirm: true, IntentKind: kind, IntentNote: "n"})
		if result.OK || result.Outcome != "rejected" {
			t.Fatalf("kind %q must be rejected: %#v", kind, result)
		}
		if !strings.Contains(result.Reason, kind) || !strings.Contains(result.Reason, "operator-request") {
			t.Fatalf("rejection reason for kind %q lacks diagnostics: %q", kind, result.Reason)
		}
		if len(result.Details) != 0 {
			t.Fatalf("rejected kind %q must never execute commands: %#v", kind, result.Details)
		}
	}
}

func TestRegistrySourceMatchesSymlinkedProjectRoot(t *testing.T) {
	realRoot := t.TempDir()
	source := t.TempDir()
	linkParent := t.TempDir()
	linkedRoot := filepath.Join(linkParent, "project-link")
	if err := os.Symlink(realRoot, linkedRoot); err != nil {
		t.Fatal(err)
	}
	// Registry records the real path; resolution is asked via the symlink.
	registry := writeRegistry(t, t.TempDir(), realRoot, source)
	isolateResolver(t, registry)
	fakeExecutable(t, source, "scripts/cos-coverage", "#!/usr/bin/env bash\necho ok\n")

	resolved, err := resolveScript(linkedRoot, "cos-coverage")
	if err != nil {
		t.Fatalf("unexpected resolve error: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cos-coverage"); resolved != want {
		t.Fatalf("resolved %q, want %q", resolved, want)
	}

	// And the inverse: registry records the symlinked path, lookup via real.
	registryReversed := writeRegistry(t, t.TempDir(), linkedRoot, source)
	isolateResolver(t, registryReversed)
	resolved, err = resolveScript(realRoot, "cos-coverage")
	if err != nil {
		t.Fatalf("unexpected reversed resolve error: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cos-coverage"); resolved != want {
		t.Fatalf("reversed resolved %q, want %q", resolved, want)
	}
}
