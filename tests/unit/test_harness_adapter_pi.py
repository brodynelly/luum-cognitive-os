"""Unit tests for the pi harness adapter (ADR-033)."""

from __future__ import annotations

import json
from pathlib import Path

from lib.harness_adapter.base import (
    HarnessName,
    SessionStart,
    TokenUsage,
    ToolUse,
    ToolUseEnd,
    ToolUseStart,
    UserPromptSubmit,
)
from lib.harness_adapter.dispatch import dispatch_event
from lib.harness_adapter.pi import PiAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pi-live-session"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestPiAdapterDetection:
    def test_detects_all_pi_event_types(self):
        for name in (
            "session.json",
            "message_user.json",
            "message_assistant_toolcall.json",
            "tool_result.json",
            "bash_execution.json",
            "model_change.json",
        ):
            assert PiAdapter.detect_harness(_fixture(name)) == HarnessName.PI, name

    def test_does_not_claim_foreign_payloads(self):
        # Claude Code hook payloads carry hook_event_name.
        assert (
            PiAdapter.detect_harness(
                {"type": "session", "hook_event_name": "SessionStart"}
            )
            is None
        )
        # OpenCode native event names.
        assert PiAdapter.detect_harness({"type": "tool.execute.before"}) is None
        # Non-dict input.
        assert PiAdapter.detect_harness("not a dict") is None
        assert PiAdapter.detect_harness(None) is None


class TestPiAdapterParse:
    def test_session_yields_session_start(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(_fixture("session.json"))
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, SessionStart)
        assert event.harness == "pi"
        assert event.session_id == "019eb3f7-2630-75c3-a668-b89ac1ecbe7d"
        assert event.cwd == "/workspace/demo-repo"
        assert event.version == "3"
        assert event.started_at > 0

    def test_user_message_yields_prompt_submit_without_leak(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(_fixture("message_user.json"))
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, UserPromptSubmit)
        assert event.harness == "pi"
        assert event.prompt_hash  # a hash, not the raw prompt
        assert event.prompt_summary is not None
        assert len(event.prompt_summary) <= 160

    def test_assistant_toolcall_yields_start_and_token_usage(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(
            _fixture("message_assistant_toolcall.json")
        )
        starts = [e for e in events if isinstance(e, ToolUseStart)]
        tokens = [e for e in events if isinstance(e, TokenUsage)]
        assert len(starts) == 1
        assert starts[0].tool_name == "read"
        assert starts[0].agent_id == "call_abc123"
        assert len(tokens) == 1
        assert tokens[0].input_tokens == 1473
        assert tokens[0].output_tokens == 224
        assert tokens[0].model == "claude-sonnet-4-6"

    def test_tool_result_yields_tooluse_end_correlated(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(_fixture("tool_result.json"))
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ToolUseEnd)
        # Correlates with the toolCall id from the assistant turn.
        assert event.agent_id == "call_abc123"
        assert event.tool_name == "read"
        assert event.exit_status == "success"

    def test_bash_execution_yields_combined_tooluse(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(_fixture("bash_execution.json"))
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ToolUse)
        assert event.tool_name == "bash"
        assert event.exit_status == "success"

    def test_model_change_is_noop(self, tmp_path):
        events = PiAdapter(project_dir=tmp_path).parse_event(_fixture("model_change.json"))
        assert events == []


class TestPiDispatch:
    def test_dispatch_routes_session_to_pi(self, tmp_path):
        result = dispatch_event(_fixture("session.json"), project_dir=tmp_path)
        assert result["harness"] == "pi"
        assert any(ev["event_type"] == "session_start" for ev in result["events"])
        assert result["output_path"]

    def test_dispatch_routes_bash_execution_to_pi(self, tmp_path):
        result = dispatch_event(_fixture("bash_execution.json"), project_dir=tmp_path)
        assert result["harness"] == "pi"
        assert any(ev["event_type"] == "tool_use" for ev in result["events"])
