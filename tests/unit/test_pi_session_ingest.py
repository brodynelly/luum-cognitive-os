"""Unit tests for the pi session ingest runner (ADR-336)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))

import pi_session_ingest as ingest  # noqa: E402

_FIXTURES = _REPO / "tests" / "fixtures" / "pi-live-session"


def _make_session(tmp_path: Path) -> Path:
    names = [
        "session.json",
        "message_user.json",
        "message_assistant_toolcall.json",
        "bash_execution.json",
    ]
    lines = [json.dumps(json.loads((_FIXTURES / n).read_text())) for n in names]
    out = tmp_path / "sess.jsonl"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _events(project_dir: Path):
    out = project_dir / ".cognitive-os/metrics/canonical-events.jsonl"
    if not out.exists():
        return []
    return [json.loads(line) for line in out.read_text().splitlines() if line.strip()]


class TestPiSessionIngest:
    def test_emits_canonical_events(self, tmp_path):
        session = _make_session(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()

        summary = ingest.run(project_dir=project, session=str(session))

        assert summary["sessions_scanned"] == 1
        assert summary["new_event_lines"] == 4
        types = {e["event_type"] for e in _events(project)}
        assert {"session_start", "user_prompt_submit", "tool_use_start", "tool_use"} <= types

    def test_ingest_is_idempotent(self, tmp_path):
        session = _make_session(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()

        first = ingest.run(project_dir=project, session=str(session))
        emitted_after_first = len(_events(project))
        second = ingest.run(project_dir=project, session=str(session))

        assert first["new_event_lines"] == 4
        assert second["new_event_lines"] == 0  # cursor blocks re-emission
        assert len(_events(project)) == emitted_after_first  # no duplication

    def test_cursor_persisted(self, tmp_path):
        session = _make_session(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        ingest.run(project_dir=project, session=str(session))
        cursor = ingest.load_cursor(project)
        assert cursor.get(str(session.resolve())) == 4
