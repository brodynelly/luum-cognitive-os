---
adr: 336
title: pi Harness Integration (Observe, Ingest, Drive)
status: accepted
implementation_status: implemented
date: '2026-06-11'
supersedes: []
superseded_by: null
implementation_files:
  - lib/harness_adapter/pi.py
  - lib/harness_adapter/base.py
  - lib/harness_adapter/dispatch.py
  - lib/compatibility_layer.py
  - lib/skill_runner.py
  - scripts/pi_session_ingest.py
  - bin/cos-pi-agent
  - bin/cos-pi-ingest
  - examples/pi-run-task/pi-task.json
  - examples/pi-run-task/README.md
  - tests/unit/test_harness_adapter_pi.py
  - tests/unit/test_pi_session_ingest.py
  - tests/unit/test_skill_runner_pi.py
  - pkg/hook/context.go
  - internal/provider/pi.go
  - internal/provider/pi_test.go
  - scripts/pi_tool_gate.py
  - bin/cos-pi-guard
  - examples/pi-extension/cos-bridge.ts
  - examples/pi-extension/README.md
  - tests/unit/test_pi_tool_gate.py
  - specs/feature-1928fafa-pi-inproc-governance.md
tier: maintainer
tags: [harness, pi, adr-033, observability, run-task, adw]
classification_basis: harness-adapter event normalization, transcript ingest runner, run-task execution gateway, and skill_runner detection — all COS-internal infrastructure with portability tests
---

# ADR-336: pi Harness Integration (Observe, Ingest, Drive)

## Status

Accepted — implemented on 2026-06-11.

## Context

`pi` (`@earendil-works/pi-coding-agent`) is a standalone CLI/TUI coding agent the
operator runs alongside Claude Code. Before this ADR the COS had no awareness of
pi: its session telemetry was a blind spot, and the COS could not drive it.

The COS already had the abstractions needed:

- **ADR-033 harness-adapter layer** (`lib/harness_adapter/`) normalizes any
  harness's native events into a canonical stream consumed by dashboards, cost
  rollups, and SLO probes. Peers: `claude_code`, `codex`, `aider`, `opencode`,
  `bare_cli`.
- **`cos run-task`** (`cmd/cos/internal/cli/run_task.go`) is a single-node
  headless runtime: it validates a task contract, creates an isolated git
  worktree, runs an arbitrary `execution.command` via `/bin/sh -c`, runs
  acceptance criteria, and writes preflight/execution/acceptance/diff/outcome/
  trust-report artifacts. `executeRunTaskAgent` runs *any* shell command — no
  per-provider Go code is required.
- **`skill_runner.detect_harness()`** resolves the active harness for portable
  skill rendering.

The decision was where to attach pi across these surfaces.

## Decision

Integrate pi at three layers, mirroring how `claude_code` is wired, plus a
detection touch — without modifying any Go code.

1. **Observe** — `lib/harness_adapter/pi.py` (`PiAdapter`): a passive
   transcript adapter (like `aider`/`opencode`) that translates pi session
   events into canonical events:
   - `session` → `SessionStart`
   - `message`/`user` → `UserPromptSubmit` (summary + hash; no raw prompt leak)
   - `message`/`assistant` → `ToolUseStart` (per `toolCall`) + `TokenUsage`
   - `message`/`toolResult` → `ToolUseEnd` (correlated via `toolCallId`)
   - `message`/`bashExecution` → `ToolUse`
   - `model_change` / `thinking_level_change` → no-op
   Registered in the `HarnessName` enum, the `dispatch.ADAPTERS` list (before the
   `bare_cli` fallback), and the `HARNESS_ADAPTERS` compatibility contract.

2. **Ingest** — `scripts/pi_session_ingest.py` + `bin/cos-pi-ingest`: replay pi
   session transcripts (`<pi-home>/agent/sessions/**/*.jsonl`) through the
   dispatcher so pi work lands in `.cognitive-os/metrics/canonical-events.jsonl`.
   A per-file line cursor (`.cognitive-os/metrics/.pi-ingest-cursor.json`) makes
   ingestion idempotent (safe to re-run from cron or a Stop hook). This is what
   actually *feeds* `PiAdapter` — without it the adapter is inert.

3. **Drive** — `bin/cos-pi-agent` + `examples/pi-run-task/pi-task.json`: a
   gateway script that builds and execs `pi -p --mode json --no-session
   --append-system-prompt <.pi/agents/<role>.md> "<task>"`, reading the task from
   `COS_TASK_DESCRIPTION` (injected by `cos run-task`). Pointed at by a run-task
   payload's `execution.command`, it lets the COS run pi inside an isolated
   worktree with acceptance gating and a trust-report — zero Go changes.
   `COS_PI_DRYRUN=1` prints the resolved command for wiring tests without
   invoking (or paying for) pi.

4. **Detect** — `skill_runner.detect_harness()` returns `"pi"` for
   `PI_SESSION_ID`/`PI_PROJECT_DIR` (or explicit `COGNITIVE_OS_HARNESS=pi`); pi
   renders SKILL.md bodies like `codex`/`bare_cli`.

## Alternatives considered

| Vector | Description | Verdict |
|--------|-------------|---------|
| **Drive via `cos run-task`** (chosen) | pi gateway as `execution.command` | Chosen — reuses the real autonomous runtime; no Go |
| **Go provider** (`internal/provider/pi.go`) | parse pi cos-bridge payloads Go-side | **Implemented** — `PiProvider` + `ProviderPi`, registered in the Registry, so pi is first-class in the Go hook engine like claude/codex |
| **Standalone ADW gateway** (tac-4 style) | bespoke Python plan→build→review loop shelling pi | Rejected — reinvents run-task's isolation/acceptance |
| **pi extension (live events + governance)** — Vector D | TypeScript pi extension emitting canonical events live and enforcing COS guards in-process | **Implemented** — `examples/pi-extension/cos-bridge.ts` + the `scripts/pi_tool_gate.py` brain (ADW `1928fafa`): live `tool_use_start`/`tool_use_end` + a blocking governance gate |
| **MCP bridge** | expose COS skills as MCP tools so pi calls COS | Deferred — inverse direction; orthogonal capability |
| **`skill_runner` rendering only** | register pi for SKILL.md rendering | Adopted as the minor Detect touch; insufficient alone (text only) |

## Consequences

- pi-driven work is now visible in the same observability/cost/telemetry plumbing
  as Claude Code, and the COS can drive pi through its existing run-task runtime.
- No Go changes; all integration is Python/Bash + config, matching the existing
  adapter pattern.
- A real pi *inference* run still requires the operator's pi/provider auth; the
  dry-run path verifies the full orchestration chain without it.
- pi now reaches full first-class parity: Observe (adapter), Ingest (runner),
  Drive (run-task), Govern (in-process `cos-bridge` extension + gate), and a Go
  provider (`PiProvider`) in the hook engine. The TS extension is grounded on
  pi's verified API but its end-to-end check still happens in a live pi session
  (install recipe in `examples/pi-extension/README.md`).
- The governance gate is a high-signal policy subset (ALWAYS_BLOCKED paths +
  unmistakably destructive commands), not a sandbox; broadening it to reuse more
  of the COS hook suite is the remaining follow-up.

## Verification

- `pytest` — `test_harness_adapter_pi.py`, `test_pi_session_ingest.py`,
  `test_skill_runner_pi.py` plus all sibling adapter + compatibility tests pass.
- `PiAdapter` parsed 16 real pi session files (99 event lines → 69 canonical
  events), routed 100% to `pi`, with no cross-harness collision.
- `cos run-task` end-to-end drove `bin/cos-pi-agent` (dry-run) in an isolated
  worktree: `status: passed`, full artifact set including `trust-report.md`.
- Ingest over real sessions is idempotent (run 2 emitted 0 new events).
