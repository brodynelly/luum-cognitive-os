package provider

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/luum/cos-dispatch/pkg/hook"
)

// piPayload is the JSON the pi cos-bridge extension (ADR-336, Vector D) sends to
// the COS hook engine. pi names its fields "tool"/"input" (vs Claude/Codex
// "tool_name"/"tool_input") and tags each call with the pi event name.
type piPayload struct {
	Event     string          `json:"event"`
	ToolName  string          `json:"tool"`
	ToolInput json.RawMessage `json:"input"`
	SessionID string          `json:"session_id"`
	CWD       string          `json:"cwd"`
	IsError   *bool           `json:"is_error,omitempty"`
	ExitCode  *int            `json:"exit_code,omitempty"`
	Output    string          `json:"output,omitempty"`
}

// piToolInput captures the tool_input fields pi exposes. pi uses "path" (not
// "file_path") and "command" for bash.
type piToolInput struct {
	Command string `json:"command,omitempty"`
	Path    string `json:"path,omitempty"`
	Content string `json:"content,omitempty"`
	Pattern string `json:"pattern,omitempty"`
	Glob    string `json:"glob,omitempty"`
}

// PiProvider adapts pi hook payloads to the canonical format.
type PiProvider struct{}

// PiSupportedEvents is the honest pi hook surface delivered by the cos-bridge
// extension: session start plus pre/post tool events (tool_call/tool_result).
var PiSupportedEvents = map[string]bool{
	"SessionStart": true,
	"PreToolUse":   true,
	"PostToolUse":  true,
}

// NewPiProvider creates a pi provider adapter.
func NewPiProvider() *PiProvider {
	return &PiProvider{}
}

func (p *PiProvider) Name() hook.Provider {
	return hook.ProviderPi
}

// Detect checks for PI_SESSION_ID or PI_PROJECT_DIR environment variables.
func (p *PiProvider) Detect() bool {
	return os.Getenv("PI_SESSION_ID") != "" || os.Getenv("PI_PROJECT_DIR") != ""
}

// Parse converts a pi cos-bridge payload into a canonical hook.Context.
func (p *PiProvider) Parse(raw []byte) (*hook.Context, error) {
	var payload piPayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("pi: parse payload: %w", err)
	}

	var ti piToolInput
	if len(payload.ToolInput) > 0 {
		if err := json.Unmarshal(payload.ToolInput, &ti); err != nil {
			return nil, fmt.Errorf("pi: parse tool_input: %w", err)
		}
	}

	pattern := ti.Pattern
	if pattern == "" {
		pattern = ti.Glob
	}

	ctx := &hook.Context{
		Provider:  hook.ProviderPi,
		Event:     mapPiEvent(payload.Event),
		ToolName:  mapPiTool(payload.ToolName),
		SessionID: payload.SessionID,
		CWD:       payload.CWD,
		RawJSON:   raw,
		ExitCode:  payload.ExitCode,
		ToolInput: hook.ToolInput{
			Command:  ti.Command,
			FilePath: ti.Path,
			Content:  ti.Content,
			Pattern:  pattern,
		},
	}

	if payload.Output != "" {
		ctx.ToolOutput = payload.Output
	}

	// pi reports tool failures via is_error rather than an exit code.
	if ctx.ExitCode == nil && payload.IsError != nil && *payload.IsError {
		one := 1
		ctx.ExitCode = &one
	}

	if mapPiEvent(payload.Event) == hook.CanonicalEventUnknown && payload.Event != "" {
		ctx.SetMetadata("parse_error_reason", "pi_unsupported_event:"+payload.Event)
	}

	if dir := os.Getenv("PI_PROJECT_DIR"); dir != "" {
		ctx.ProjectDir = dir
	} else if payload.CWD != "" {
		ctx.ProjectDir = payload.CWD
	}

	return ctx, nil
}

// BuildResponse returns the {block, reason} shape the pi cos-bridge extension
// enforces (it returns it from pi.on("tool_call")).
func (p *PiProvider) BuildResponse(hookCtx *hook.Context, decision string, message string, additionalContext string) any {
	block := decision == "deny" || decision == "block"
	reason := message
	if additionalContext != "" {
		reason = message + "\n\n" + additionalContext
	}
	return map[string]any{
		"block":  block,
		"reason": reason,
	}
}

// ConfigPaths returns pi config file paths.
func (p *PiProvider) ConfigPaths(projectDir string) []string {
	return []string{
		filepath.Join(projectDir, ".pi", "damage-control-rules.yaml"),
		filepath.Join(projectDir, ".pi", "agent", "settings.json"),
	}
}

// SupportedEvents returns pi lifecycle event names this provider can normalize.
func (p *PiProvider) SupportedEvents() map[string]bool {
	return PiSupportedEvents
}

// mapPiEvent maps pi event names to canonical events.
func mapPiEvent(event string) hook.CanonicalEvent {
	switch event {
	case "tool_call":
		return hook.CanonicalEventBeforeTool
	case "tool_result":
		return hook.CanonicalEventAfterTool
	case "session_start":
		return hook.CanonicalEventSessionStart
	default:
		return hook.CanonicalEventUnknown
	}
}

// mapPiTool maps pi's lowercase tool names to canonical tool types.
func mapPiTool(tool string) hook.ToolType {
	switch tool {
	case "bash":
		return hook.ToolBash
	case "read":
		return hook.ToolRead
	case "write":
		return hook.ToolWrite
	case "edit":
		return hook.ToolEdit
	case "grep":
		return hook.ToolGrep
	case "glob", "find", "ls":
		return hook.ToolGlob
	default:
		return hook.ToolUnknown
	}
}
