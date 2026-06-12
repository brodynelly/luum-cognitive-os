"""Unit tests for the pi governance gate (ADR-336 / Vector D)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))

import pi_tool_gate as gate  # noqa: E402


class TestPathPolicy:
    def test_blocks_secret_paths(self):
        for path in [".env", ".env.local", "id_rsa.key", "server.pem", "cert.p12",
                     "secrets/db.yaml", "config/credentials.json", "etc/password.txt",
                     ".git/config"]:
            assert gate.blocked_path_reason(path), path

    def test_allows_ordinary_paths(self):
        for path in ["src/app.ts", "README.md", "lib/foo.py", ".environment", "envoy.yaml"]:
            assert gate.blocked_path_reason(path) is None, path

    def test_write_to_env_blocks(self):
        d = gate.decide({"tool": "write", "input": {"path": ".env"}})
        assert d["block"] is True and ".env" in d["reason"]

    def test_read_secret_blocks(self):
        d = gate.decide({"tool": "read", "input": {"path": "secrets/key.pem"}})
        assert d["block"] is True

    def test_read_source_allows(self):
        d = gate.decide({"tool": "read", "input": {"path": "src/app.ts"}})
        assert d["block"] is False


class TestBashPolicy:
    def test_blocks_destructive(self):
        for cmd in ["rm -rf /", "rm -rf ~", "rm -fr /*", ":(){:|:&};:",
                    "git push --force origin main", "chmod -R 777 /",
                    # flag-order / long-flag evasion variants (ADW fix attempt 1)
                    "rm -r -f /", "rm --recursive --force /", "rm -f -r ~"]:
            d = gate.decide({"tool": "bash", "input": {"command": cmd}})
            assert d["block"] is True, cmd

    def test_blocks_secret_reference(self):
        d = gate.decide({"tool": "bash", "input": {"command": "cat .env"}})
        assert d["block"] is True

    def test_allows_normal_commands(self):
        for cmd in ["ls -la", "git status", "npm test", "rm -rf node_modules",
                    "rm -f stale.txt", "rm -rf ./dist", "rmdir build",
                    "git push --force-with-lease origin feature"]:
            d = gate.decide({"tool": "bash", "input": {"command": cmd}})
            assert d["block"] is False, cmd


class TestLiveEmissionAndContract:
    def test_run_emits_canonical_event(self, tmp_path):
        d = gate.run({"tool": "read", "input": {"path": "src/app.ts"}}, tmp_path)
        assert d["event_emitted"] is True
        out = tmp_path / ".cognitive-os/metrics/canonical-events.jsonl"
        assert out.exists()
        events = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
        assert any(e["event_type"] == "tool_use_start" and e["tool_name"] == "read" for e in events)

    def test_shim_contract(self, tmp_path):
        # The exact descriptor cos-bridge.ts sends: {tool, input, cwd}.
        descriptor = {"tool": "write", "input": {"path": "notes.md"}, "cwd": str(tmp_path)}
        d = gate.run(descriptor, tmp_path)
        assert set(d) >= {"block", "reason", "event_emitted"}
        assert d["block"] is False

    def test_empty_descriptor_fails_open(self):
        assert gate.decide({})["block"] is False

    def test_result_phase_emits_tool_use_end(self, tmp_path):
        d = gate.run(
            {"tool": "read", "input": {"path": "a"}, "phase": "result",
             "id": "c1", "is_error": False},
            tmp_path,
        )
        assert d["block"] is False
        assert d["event_emitted"] is True
        out = tmp_path / ".cognitive-os/metrics/canonical-events.jsonl"
        events = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
        assert any(
            e["event_type"] == "tool_use_end" and e["agent_id"] == "c1" for e in events
        )
