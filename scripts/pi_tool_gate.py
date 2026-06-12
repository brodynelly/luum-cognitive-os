#!/usr/bin/env python3
"""COS in-process governance + live-telemetry gate for pi (ADR-336 / Vector D).

The pi-side extension (``examples/pi-extension/cos-bridge.ts``) calls this gate
on every pi ``tool_call``. The gate:

1. emits a **live** canonical event by feeding a synthetic pi ``toolCall`` event
   through ``lib.harness_adapter.dispatch`` — reusing the ADR-336 ``PiAdapter``
   (no parallel emission path); and
2. returns a governance **decision** the extension enforces (``block`` aborts the
   pi tool call, exactly like a Claude Code ``PreToolUse`` deny).

Input  (stdin or ``--json``):
    {"tool": "bash", "input": {...}, "cwd": "/repo", "session_id": "...", "id": "..."}
Output (stdout):
    {"block": false, "reason": "", "event_emitted": true}

Policy (high-signal subset; deeper hook reuse is a documented follow-up):
- BLOCK read/write/edit/grep of ALWAYS_BLOCKED paths (lib/agent_permissions.py).
- BLOCK bash that references those paths or is unmistakably destructive.
- Default ALLOW. Internal errors default to ALLOW (fail-open) so telemetry never
  bricks pi; the fault is surfaced in ``reason``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reuse the canonical blocked-path policy; fall back to a literal copy if the
# import surface ever moves (keeps the gate self-contained for portability tests).
try:
    from lib.agent_permissions import AgentPermissionManager

    ALWAYS_BLOCKED: List[str] = list(AgentPermissionManager.ALWAYS_BLOCKED)
except Exception:  # pragma: no cover - defensive fallback
    ALWAYS_BLOCKED = [
        ".env", ".env.*", "*.key", "*.pem", "*.p12",
        "secrets/*", "**/credentials*", "**/password*", ".git/config",
    ]

# Literal cores used to spot blocked paths referenced inside a bash command.
_BLOCKED_BASH_TOKENS = (
    ".env", ".pem", ".key", ".p12", "id_rsa", "secrets/", "credentials",
    ".git/config",
)

_DESTRUCTIVE = [
    (r":\(\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:", "fork bomb"),
    (r"\b(?:mkfs(?:\.\w+)?|dd)\b[^\n]*\bof=/dev/(?:sd|nvme|disk)", "raw disk write/format"),
    (r">\s*/dev/(?:sd|nvme|disk)", "raw disk overwrite"),
    (r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)", "recursive chmod 777 on root"),
    (r"\bgit\s+push\b[^\n]*--force(?!-with-lease)\b[^\n]*\b(?:main|master)\b",
     "force-push to a protected branch"),
]


def _segments(path: str) -> List[str]:
    posix = str(path).replace("\\", "/").strip()
    return [s for s in posix.split("/") if s and s != "."]


def blocked_path_reason(path: Optional[str]) -> Optional[str]:
    """Return the matched ALWAYS_BLOCKED pattern for ``path``, or None."""
    if not path:
        return None
    segs = _segments(path)
    base = segs[-1] if segs else str(path)
    for pat in ALWAYS_BLOCKED:
        simple = pat[3:] if pat.startswith("**/") else pat  # **/credentials* -> credentials*
        if fnmatch.fnmatch(base, simple):
            return pat
        if "/" in simple:
            dir_part = simple.split("/", 1)[0]  # secrets, .git
            if dir_part in segs:
                return pat
    return None


def _rm_hits_root(command: str) -> bool:
    """True if ``command`` is an ``rm`` with recursive AND force flags (in any
    order or long form) targeting a root-ish path (/, ~, $HOME, /*)."""
    if not re.search(r"\brm\b", command):
        return False
    has_recursive = bool(
        re.search(r"(?:^|\s)-[a-zA-Z]*r[a-zA-Z]*\b", command)
        or re.search(r"--recursive\b", command)
    )
    has_force = bool(
        re.search(r"(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*\b", command)
        or re.search(r"--force\b", command)
    )
    if not (has_recursive and has_force):
        return False
    return bool(
        re.search(r"(?:\s|=)(?:/|~|/\*|\$HOME|\$\{HOME\})(?:\s|;|&|\||$)", command)
    )


def destructive_bash_reason(command: Optional[str]) -> Optional[str]:
    if not command:
        return None
    norm = re.sub(r"\s+", " ", command.strip())
    nospace = norm.replace(" ", "")
    if ":(){:|:&};:" in nospace:
        return "fork bomb"
    if _rm_hits_root(norm):
        return "recursive force-delete of root/home"
    for pattern, reason in _DESTRUCTIVE:
        if re.search(pattern, norm):
            return reason
    return None


def bash_blocked_path_reason(command: Optional[str]) -> Optional[str]:
    if not command:
        return None
    for token in _BLOCKED_BASH_TOKENS:
        if token in command:
            return f"references protected path/token: {token}"
    return None


def decide(descriptor: Dict[str, Any]) -> Dict[str, Any]:
    """Return {'block': bool, 'reason': str} for a pi tool-call descriptor."""
    tool = str(descriptor.get("tool") or descriptor.get("toolName") or "").lower()
    tool_input = descriptor.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool in ("write", "edit", "read", "grep", "find", "ls"):
        path = tool_input.get("path")
        reason = blocked_path_reason(path)
        if reason:
            verb = "modify" if tool in ("write", "edit") else "access"
            return {"block": True, "reason": f"COS: refuses to {verb} protected path ({reason})"}

    if tool == "bash":
        command = tool_input.get("command")
        reason = destructive_bash_reason(command)
        if reason:
            return {"block": True, "reason": f"COS: blocked destructive command ({reason})"}
        reason = bash_blocked_path_reason(command)
        if reason:
            return {"block": True, "reason": f"COS: command {reason}"}

    return {"block": False, "reason": ""}


def _phase(descriptor: Dict[str, Any]) -> str:
    return str(descriptor.get("phase") or "call").lower()


def emit_live_event(descriptor: Dict[str, Any], project_dir: Path) -> bool:
    """Emit one live canonical event by reusing the ADR-336 PiAdapter.

    ``phase == "call"`` (default, pre-execution) emits a ``tool_use_start``;
    ``phase == "result"`` (pi ``tool_result``) emits a correlated ``tool_use_end``.
    """
    try:
        from lib.harness_adapter.dispatch import dispatch_event
    except Exception:
        return False
    call_id = str(
        descriptor.get("id")
        or "pi-gate-" + hashlib.sha1(
            json.dumps(descriptor, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:10]
    )
    tool = descriptor.get("tool") or descriptor.get("toolName")
    if _phase(descriptor) == "result":
        synthetic = {
            "type": "message",
            "id": call_id,
            "timestamp": descriptor.get("timestamp"),
            "message": {
                "role": "toolResult",
                "toolCallId": call_id,
                "toolName": tool,
                "isError": bool(descriptor.get("is_error")),
                "content": [],
            },
        }
    else:
        synthetic = {
            "type": "message",
            "id": call_id,
            "timestamp": descriptor.get("timestamp"),
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": call_id,
                        "name": tool,
                        "arguments": descriptor.get("input") or {},
                    }
                ],
                "responseId": "pi-gate",
                "stopReason": "toolUse",
            },
        }
    try:
        result = dispatch_event(json.dumps(synthetic), project_dir=project_dir)
        return result.get("harness") == "pi" and bool(result.get("events"))
    except Exception:
        return False


def run(descriptor: Dict[str, Any], project_dir: Path) -> Dict[str, Any]:
    emitted = emit_live_event(descriptor, project_dir)
    # Results are telemetry only — governance gates pre-execution (phase "call").
    if _phase(descriptor) == "result":
        return {"block": False, "reason": "", "event_emitted": emitted}
    decision = decide(descriptor)
    decision["event_emitted"] = emitted
    return decision


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="COS governance gate for pi (ADR-336).")
    ap.add_argument("--json", help="tool-call descriptor JSON (else read stdin)")
    ap.add_argument(
        "--project-dir",
        default=os.environ.get("COGNITIVE_OS_PROJECT_DIR") or os.getcwd(),
    )
    ns = ap.parse_args(argv)

    raw = ns.json if ns.json is not None else sys.stdin.read()
    try:
        descriptor = json.loads(raw) if raw.strip() else {}
        if not isinstance(descriptor, dict):
            descriptor = {}
    except (json.JSONDecodeError, ValueError):
        # Fail-open: never block pi on a malformed descriptor.
        print(json.dumps({"block": False, "reason": "gate: invalid descriptor", "event_emitted": False}))
        return 0

    print(json.dumps(run(descriptor, Path(ns.project_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
