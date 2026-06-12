package provider

import (
	"encoding/json"
	"testing"

	"github.com/luum/cos-dispatch/pkg/hook"
)

func TestPiProvider_Name(t *testing.T) {
	if got := NewPiProvider().Name(); got != hook.ProviderPi {
		t.Fatalf("Name() = %q, want %q", got, hook.ProviderPi)
	}
}

func TestPiProvider_Detect(t *testing.T) {
	p := NewPiProvider()

	t.Setenv("PI_SESSION_ID", "")
	t.Setenv("PI_PROJECT_DIR", "")
	if p.Detect() {
		t.Fatal("Detect() = true with no pi env, want false")
	}

	t.Setenv("PI_SESSION_ID", "019eb3f7-2630-75c3")
	if !p.Detect() {
		t.Fatal("Detect() = false with PI_SESSION_ID set, want true")
	}
}

func TestPiProvider_ParseToolCallBash(t *testing.T) {
	raw := []byte(`{"event":"tool_call","tool":"bash","input":{"command":"rm -rf /"},"cwd":"/repo","session_id":"s1"}`)
	ctx, err := NewPiProvider().Parse(raw)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if ctx.Provider != hook.ProviderPi {
		t.Errorf("Provider = %q, want pi", ctx.Provider)
	}
	if ctx.Event != hook.CanonicalEventBeforeTool {
		t.Errorf("Event = %q, want before_tool", ctx.Event)
	}
	if ctx.ToolName != hook.ToolBash {
		t.Errorf("ToolName = %q, want Bash", ctx.ToolName)
	}
	if ctx.GetCommand() != "rm -rf /" {
		t.Errorf("Command = %q", ctx.GetCommand())
	}
	if ctx.CWD != "/repo" || ctx.SessionID != "s1" {
		t.Errorf("CWD/SessionID = %q/%q", ctx.CWD, ctx.SessionID)
	}
}

func TestPiProvider_ParseWriteUsesPath(t *testing.T) {
	raw := []byte(`{"event":"tool_call","tool":"write","input":{"path":".env","content":"x"}}`)
	ctx, err := NewPiProvider().Parse(raw)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if ctx.ToolName != hook.ToolWrite {
		t.Errorf("ToolName = %q, want Write", ctx.ToolName)
	}
	if ctx.GetFilePath() != ".env" {
		t.Errorf("FilePath = %q, want .env", ctx.GetFilePath())
	}
	if !ctx.IsFileTool() {
		t.Error("IsFileTool() = false, want true")
	}
}

func TestPiProvider_ParseToolResultErrorSetsExitCode(t *testing.T) {
	raw := []byte(`{"event":"tool_result","tool":"read","input":{"path":"a"},"is_error":true}`)
	ctx, err := NewPiProvider().Parse(raw)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if ctx.Event != hook.CanonicalEventAfterTool {
		t.Errorf("Event = %q, want after_tool", ctx.Event)
	}
	if ctx.ExitCode == nil || *ctx.ExitCode != 1 {
		t.Errorf("ExitCode from is_error not set to 1: %v", ctx.ExitCode)
	}
}

func TestPiProvider_ParseUnknownEventFlagsGap(t *testing.T) {
	raw := []byte(`{"event":"turn_end","tool":"","input":{}}`)
	ctx, err := NewPiProvider().Parse(raw)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if ctx.Event != hook.CanonicalEventUnknown {
		t.Errorf("Event = %q, want unknown", ctx.Event)
	}
	if ctx.Metadata["parse_error_reason"] != "pi_unsupported_event:turn_end" {
		t.Errorf("missing coverage-gap metadata: %v", ctx.Metadata)
	}
}

func TestPiProvider_BuildResponse(t *testing.T) {
	p := NewPiProvider()

	deny := p.BuildResponse(nil, "deny", "no secrets", "").(map[string]any)
	if deny["block"] != true {
		t.Errorf("deny block = %v, want true", deny["block"])
	}
	if deny["reason"] != "no secrets" {
		t.Errorf("reason = %v", deny["reason"])
	}

	allow := p.BuildResponse(nil, "allow", "", "").(map[string]any)
	if allow["block"] != false {
		t.Errorf("allow block = %v, want false", allow["block"])
	}

	if _, err := json.Marshal(deny); err != nil {
		t.Fatalf("response not JSON-serializable: %v", err)
	}
}

func TestPiProvider_RegisteredInRegistry(t *testing.T) {
	if _, ok := NewRegistry().Get(hook.ProviderPi); !ok {
		t.Fatal("pi provider not found in registry")
	}
}
