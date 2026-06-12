#!/usr/bin/env python3
"""Ingest pi session transcripts into the canonical event stream (ADR-336).

pi (``@earendil-works/pi-coding-agent``) writes one JSON event per line to
``<pi-home>/agent/sessions/<project>/<ts>_<uuid>.jsonl``. This script replays
those lines through :mod:`lib.harness_adapter.dispatch` so pi-driven work lands
in ``.cognitive-os/metrics/canonical-events.jsonl`` next to Claude Code, Codex,
Aider, and OpenCode — i.e. it is what actually *feeds* the ADR-033 PiAdapter.

A per-file cursor (``.cognitive-os/metrics/.pi-ingest-cursor.json``) records how
many lines of each session file were already ingested, so re-running (from a
cron, a Stop hook, or by hand) never double-emits.

Usage::

    pi_session_ingest.py [--pi-home DIR] [--session FILE] [--project-dir DIR]
                         [--json]

With no ``--session``/``--pi-home`` it auto-discovers pi sessions under the
first existing of: ``$PI_HOME``, ``~/.pi``, ``~/github/.pi``, ``./.pi``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make ``lib`` importable when run as a standalone script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.harness_adapter.dispatch import dispatch_event  # noqa: E402

CURSOR_REL = ".cognitive-os/metrics/.pi-ingest-cursor.json"


def discover_pi_home(override: Optional[str] = None) -> Optional[Path]:
    """Return the first existing pi home directory (the one containing agent/)."""
    candidates: List[Path] = []
    if override:
        candidates.append(Path(override))
    env = os.environ.get("PI_HOME")
    if env:
        candidates.append(Path(env))
    candidates.append(Path.home() / ".pi")
    candidates.append(Path.home() / "github" / ".pi")
    candidates.append(Path.cwd() / ".pi")
    for cand in candidates:
        if (cand / "agent" / "sessions").is_dir():
            return cand
    return None


def find_sessions(pi_home: Path) -> List[Path]:
    """All pi session transcript files under ``<pi_home>/agent/sessions``."""
    root = pi_home / "agent" / "sessions"
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())


def load_cursor(project_dir: Path) -> Dict[str, int]:
    path = project_dir / CURSOR_REL
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def save_cursor(project_dir: Path, cursor: Dict[str, int]) -> None:
    path = project_dir / CURSOR_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor, sort_keys=True, indent=2), encoding="utf-8")


def ingest_file(
    session_path: Path,
    project_dir: Path,
    cursor: Dict[str, int],
) -> Dict[str, int]:
    """Dispatch new lines of one session file; update ``cursor`` in place.

    Returns ``{"lines": N_new, "events": N_emitted}``. Lines already counted in
    ``cursor`` (by absolute path) are skipped, making ingestion idempotent.
    """
    key = str(session_path.resolve())
    already = cursor.get(key, 0)
    lines = 0
    events = 0
    new_index = already
    try:
        raw = session_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"lines": 0, "events": 0}
    for idx, line in enumerate(raw):
        if idx < already:
            continue
        new_index = idx + 1
        line = line.strip()
        if not line:
            continue
        result = dispatch_event(line, project_dir=project_dir)
        if result.get("harness") == "pi":
            lines += 1
            events += len(result.get("events") or [])
    cursor[key] = max(already, new_index, len(raw))
    return {"lines": lines, "events": events}


def run(
    *,
    project_dir: Path,
    pi_home: Optional[str] = None,
    session: Optional[str] = None,
) -> Dict[str, object]:
    """Ingest one session (``session``) or all discovered sessions."""
    cursor = load_cursor(project_dir)
    targets: List[Path] = []
    if session:
        targets = [Path(session)]
        home_used: Optional[str] = None
    else:
        home = discover_pi_home(pi_home)
        home_used = str(home) if home else None
        if home is not None:
            targets = find_sessions(home)

    total_lines = 0
    total_events = 0
    for path in targets:
        stats = ingest_file(path, project_dir, cursor)
        total_lines += stats["lines"]
        total_events += stats["events"]
    save_cursor(project_dir, cursor)

    return {
        "pi_home": home_used,
        "sessions_scanned": len(targets),
        "new_event_lines": total_lines,
        "canonical_events_emitted": total_events,
        "output": str(project_dir / ".cognitive-os/metrics/canonical-events.jsonl"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest pi session transcripts (ADR-336).")
    ap.add_argument("--pi-home", help="pi home dir (containing agent/sessions/)")
    ap.add_argument("--session", help="ingest a single session .jsonl file")
    ap.add_argument(
        "--project-dir",
        default=os.environ.get("COGNITIVE_OS_PROJECT_DIR") or os.getcwd(),
        help="repo root where .cognitive-os/metrics/ is written",
    )
    ap.add_argument("--json", action="store_true", help="emit a JSON summary")
    ns = ap.parse_args(argv)

    summary = run(
        project_dir=Path(ns.project_dir),
        pi_home=ns.pi_home,
        session=ns.session,
    )
    if ns.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"pi ingest: {summary['sessions_scanned']} session(s), "
            f"{summary['new_event_lines']} new event line(s) → "
            f"{summary['canonical_events_emitted']} canonical event(s)\n"
            f"  {summary['output']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
