package tui

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunActionRequiresAllowlistAndConfirmation(t *testing.T) {
	root := t.TempDir()
	fakeExecutable(t, root, "scripts/cos-coverage", "#!/usr/bin/env bash\necho refreshed\n")

	unknown := RunAction(root, "shell", ActionOptions{Confirm: true})
	if unknown.OK || unknown.Outcome != "rejected" || !strings.Contains(unknown.Reason, "not allowlisted") {
		t.Fatalf("unexpected unknown action result: %#v", unknown)
	}

	unconfirmed := RunAction(root, "refresh-coverage", ActionOptions{})
	if unconfirmed.OK || unconfirmed.Outcome != "rejected" || !strings.Contains(unconfirmed.Reason, "--confirm") {
		t.Fatalf("unexpected unconfirmed result: %#v", unconfirmed)
	}
	if fileExists(filepath.Join(root, ".cognitive-os", "metrics", "tui-actions.jsonl")) {
		t.Fatalf("unconfirmed action wrote a receipt")
	}
}

func TestRunActionWritesReceiptForConfirmedRefresh(t *testing.T) {
	root := t.TempDir()
	fakeExecutable(t, root, "scripts/cos-coverage", "#!/usr/bin/env bash\necho '{\"ok\":true}'\n")

	result := RunAction(root, "refresh-coverage", ActionOptions{Confirm: true})

	if !result.OK || result.Outcome != "success" {
		t.Fatalf("unexpected action result: %#v", result)
	}
	if result.Receipt == "" {
		t.Fatalf("receipt path was not recorded")
	}
	data, err := os.ReadFile(result.Receipt)
	if err != nil {
		t.Fatal(err)
	}
	var row map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(data))), &row); err != nil {
		t.Fatal(err)
	}
	if row["schema_version"] != "cos-tui-action-receipt.v1" || row["surface_id"] != "tui" || row["mode"] != "operable" {
		t.Fatalf("unexpected receipt row: %#v", row)
	}
}

func TestInboxAckRequiresMessageID(t *testing.T) {
	root := t.TempDir()
	result := RunAction(root, "inbox-ack", ActionOptions{Confirm: true})
	if result.OK || result.Outcome != "rejected" || !strings.Contains(result.Reason, "--message-id") {
		t.Fatalf("unexpected inbox ack result: %#v", result)
	}
}

func fakeExecutable(t *testing.T, root, rel, content string) {
	t.Helper()
	path := filepath.Join(root, rel)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestResolveActionScriptConsumerFallback(t *testing.T) {
	// Consumer project without scripts/ falls back to the COS source
	// recorded in install-meta.json.
	source := t.TempDir()
	if err := os.MkdirAll(filepath.Join(source, "scripts"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "scripts", "cos-coverage"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	project := t.TempDir()
	if err := os.MkdirAll(filepath.Join(project, ".cognitive-os"), 0o755); err != nil {
		t.Fatal(err)
	}
	meta, _ := json.Marshal(map[string]string{"source": source})
	if err := os.WriteFile(filepath.Join(project, ".cognitive-os", "install-meta.json"), meta, 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := resolveActionScript(project, "cos-coverage")
	if err != nil {
		t.Fatalf("fallback resolution failed: %v", err)
	}
	if want := filepath.Join(source, "scripts", "cos-coverage"); got != want {
		t.Fatalf("got %q want %q", got, want)
	}

	// A project-local script must win over the source fallback.
	if err := os.MkdirAll(filepath.Join(project, "scripts"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(project, "scripts", "cos-coverage"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err = resolveActionScript(project, "cos-coverage")
	if err != nil {
		t.Fatal(err)
	}
	if want := filepath.Join(project, "scripts", "cos-coverage"); got != want {
		t.Fatalf("local script should win: got %q want %q", got, want)
	}

	// Missing everywhere -> explicit error, not a phantom command.
	if _, err := resolveActionScript(t.TempDir(), "cos-coverage"); err == nil {
		t.Fatal("expected error when script is absent everywhere")
	}
}
