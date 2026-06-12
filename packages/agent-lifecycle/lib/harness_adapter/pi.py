"""pi harness adapter (ADR-033).

pi (``@earendil-works/pi-coding-agent``) records each turn as one JSON line in a
session transcript under ``.pi/agent/sessions/<project>/<ts>_<uuid>.jsonl``.

Top-level event ``type`` values:

- ``session``                -> :class:`SessionStart`
- ``model_change``           -> no-op (provider/model config, not telemetry)
- ``thinking_level_change``  -> no-op (config)
- ``message``                -> wraps a nested object keyed by ``role``:

  * ``user``           -> :class:`UserPromptSubmit`
  * ``assistant``      -> :class:`ToolUseStart` (one per ``toolCall`` content
                          item) + :class:`TokenUsage` (from ``usage``)
  * ``toolResult``     -> :class:`ToolUseEnd` (correlates via ``toolCallId``)
  * ``bashExecution``  -> :class:`ToolUse` (combined; ``bash`` + ``exitCode``)

Like the aider and opencode adapters this is a *passive transcript* adapter: it
does not depend on hook stdin and never echoes raw prompt or command bodies into
the canonical stream — only bounded summaries and content hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from .base import (
    CanonicalEvent,
    HarnessAdapter,
    HarnessName,
    ParseError,
    SessionStart,
    TokenUsage,
    ToolUse,
    ToolUseEnd,
    ToolUseStart,
    UserPromptSubmit,
    now_epoch,
)


#: Top-level ``type`` values pi emits. Used by :meth:`detect_harness`.
_PI_EVENT_TYPES = frozenset(
    {"session", "model_change", "thinking_level_change", "message"}
)

#: ``message.role`` values that are unique to pi (no other supported harness
#: uses these), so they are sufficient on their own to claim the payload.
_PI_DISTINCTIVE_ROLES = frozenset({"toolResult", "bashExecution"})


class PiAdapter(HarnessAdapter):
    """Adapter for pi coding-agent session transcript events."""

    name: ClassVar[HarnessName] = HarnessName.PI
    default_output: ClassVar[str] = ".cognitive-os/metrics/canonical-events.jsonl"

    @classmethod
    def detect_harness(cls, raw: Any) -> Optional[HarnessName]:
        if not isinstance(raw, dict):
            return None
        if raw.get("harness") == cls.name.value:
            return cls.name
        event_type = raw.get("type")
        if event_type not in _PI_EVENT_TYPES:
            return None
        # ``model_change`` / ``thinking_level_change`` names are pi-specific.
        if event_type in ("model_change", "thinking_level_change"):
            return cls.name
        # ``session``: pi's shape is {type, version, id, timestamp, cwd} and has
        # none of the hook/wrapper fields the other adapters key on.
        if event_type == "session":
            if (
                "version" in raw
                and "cwd" in raw
                and "id" in raw
                and "hook_event_name" not in raw
                and "payload" not in raw
                and "message" not in raw
            ):
                return cls.name
            return None
        # ``message``: pi wraps a nested ``message`` dict and tags the line with
        # top-level ``id``/``parentId``. Distinctive roles or assistant response
        # markers confirm it is pi rather than another transcript format.
        if event_type == "message" and isinstance(raw.get("message"), dict):
            msg = raw["message"]
            role = msg.get("role")
            if role in _PI_DISTINCTIVE_ROLES:
                return cls.name
            if role == "assistant" and ("responseId" in msg or "stopReason" in msg):
                return cls.name
            if role == "user" and "id" in raw and "parentId" in raw:
                return cls.name
        return None

    def parse_event(self, raw: Dict[str, Any]) -> List[CanonicalEvent]:
        event_type = raw.get("type")

        if event_type == "session":
            return [
                SessionStart(
                    session_id=str(raw.get("id") or "pi-session"),
                    started_at=_to_epoch(raw.get("timestamp")),
                    harness=self.name.value,
                    cwd=raw.get("cwd"),
                    source="pi_session",
                    version=(
                        str(raw["version"]) if raw.get("version") is not None else None
                    ),
                )
            ]

        # Benign configuration events carry no telemetry worth normalizing.
        if event_type in ("model_change", "thinking_level_change"):
            return []

        if event_type == "message":
            return self._parse_message(raw)

        return [
            ParseError(
                source_line=_safe_json(raw),
                adapter=self.name.value,
                reason="unsupported_pi_event",
                session_id=_session_id(raw),
            )
        ]

    # ------------------------------ internals ------------------------------

    def _parse_message(self, raw: Dict[str, Any]) -> List[CanonicalEvent]:
        msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
        role = msg.get("role")
        ts = _to_epoch(raw.get("timestamp") or msg.get("timestamp"))
        session_id = _session_id(raw)
        event_id = str(raw.get("id") or "")

        if role == "user":
            text = _first_text(msg.get("content"))
            return [
                UserPromptSubmit(
                    session_id=session_id,
                    submitted_at=ts,
                    harness=self.name.value,
                    prompt_summary=_summarize(text),
                    prompt_hash=_hash(text or ""),
                )
            ]

        if role == "assistant":
            out: List[CanonicalEvent] = []
            for item in msg.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "toolCall":
                    out.append(
                        ToolUseStart(
                            agent_id=str(
                                item.get("id")
                                or _hash(_safe_json(item.get("arguments") or {}))
                            ),
                            tool_name=str(item.get("name") or "pi_tool"),
                            started_at=ts,
                            tool_input_summary=_summarize(
                                _safe_json(item.get("arguments") or {})
                            ),
                            session_id=session_id,
                        )
                    )
            usage = msg.get("usage")
            if isinstance(usage, dict):
                out.append(
                    TokenUsage(
                        agent_id=event_id,
                        ts=ts,
                        input_tokens=_as_int(usage.get("input"), 0) or 0,
                        output_tokens=_as_int(usage.get("output"), 0) or 0,
                        cache_read=_as_int(usage.get("cacheRead")),
                        cache_creation=_as_int(usage.get("cacheWrite")),
                        model=msg.get("model"),
                        session_id=session_id,
                    )
                )
            return out

        if role == "toolResult":
            return [
                ToolUseEnd(
                    agent_id=str(msg.get("toolCallId") or ""),
                    tool_name=str(msg.get("toolName") or "pi_tool"),
                    ended_at=ts,
                    exit_status="error" if msg.get("isError") else "success",
                    session_id=session_id,
                )
            ]

        if role == "bashExecution":
            code = msg.get("exitCode")
            ok = code in (0, "0", None) and not msg.get("cancelled")
            return [
                ToolUse(
                    agent_id=event_id,
                    tool_name="bash",
                    started_at=ts,
                    exit_status="success" if ok else "error",
                    tool_input_hash=_hash(str(msg.get("command") or "")),
                    session_id=session_id,
                )
            ]

        return [
            ParseError(
                source_line=_safe_json({"type": "message", "role": role}),
                adapter=self.name.value,
                reason="unsupported_pi_message_role",
                session_id=session_id,
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_id(raw: Dict[str, Any]) -> Optional[str]:
    return (
        raw.get("session_id")
        or raw.get("sessionId")
        or os.environ.get("COGNITIVE_OS_SESSION_ID")
        or os.environ.get("PI_SESSION_ID")
    )


def _first_text(content: Any) -> Optional[str]:
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text")
    if isinstance(content, str):
        return content
    return None


def _to_epoch(value: Any) -> float:
    """Parse pi timestamps (ISO-8601 strings or epoch s/ms) into epoch seconds."""
    if value is None:
        return now_epoch()
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e12 else v
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return now_epoch()
    return now_epoch()


def _summarize(value: Any, limit: int = 160) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else _safe_json(value)
    return text[:limit]


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)[:500]
    except TypeError:
        return str(value)[:500]


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
