# Feature Spec: pi in-process governance bridge (Vector D)

**ADW ID:** 1928fafa
**Workflow:** plan_build_review_fix
**Date:** 2026-06-11
**Related:** ADR-336 (pi harness integration), ADR-033 (harness adapters)

## Summary

Move the `pi` harness from **observed-from-outside** to **governed-from-inside**.
Today the COS can watch pi (post-hoc transcript adapter, ADR-336 Observe) and
launch it (`cos run-task`, ADR-336 Drive), but **none of the COS's blocking
governance reaches inside pi's process** — pi self-governs only via its own
`damage-control-rules.yaml`. This feature adds a pi-side extension that, on every
pi tool call, (a) emits a **live** canonical event and (b) consults a COS gate
that can **block** the call — the same role Claude Code's `PreToolUse` hooks play.

## Architecture

A thin TS shim delegates to a testable COS-side gate:

```
pi tool_call ──► extensions/cos-bridge.ts ──(JSON on stdin)──► bin/cos-pi-guard
                       │                                          │
                       │                            scripts/pi_tool_gate.py:
                       │                              1. emit live canonical event
                       │                                 (reuses PiAdapter+dispatch)
                       │                              2. governance decision
                       │                                 (ALWAYS_BLOCKED paths +
                       │                                  destructive-command policy)
                       ◄──────(JSON {block,reason})──────┘
              return {block, reason} to pi
```

The **brain** (decision + event emission) is Python — fully unit-testable. The
**shim** mirrors the verified API of pi's own `damage-control.ts`
(`pi.on("tool_call", …) => {block, reason}`), so live behaviour is identical in
shape to an extension pi already runs.

## Requirements

- **R1** — `scripts/pi_tool_gate.py`: read a pi tool-call descriptor
  `{tool, input, cwd?, session_id?}` from stdin/argv; return JSON
  `{"block": bool, "reason": str, "event_emitted": bool}` on stdout, exit 0.
- **R2** — Governance: BLOCK writes/edits to `ALWAYS_BLOCKED` paths
  (`lib/agent_permissions.py`: `.env`, `.env.*`, `*.key`, `*.pem`, `secrets/*`,
  credentials, `.git/config`) and bash commands that reference them; BLOCK
  unmistakably destructive bash (`rm -rf /`, `rm -rf ~`, `git push --force` to
  protected branches, `:(){:|:&};:`). Default ALLOW.
- **R3** — Observability: on every call, emit one live canonical event to
  `.cognitive-os/metrics/canonical-events.jsonl` by feeding a synthetic pi
  assistant `toolCall` event through `lib.harness_adapter.dispatch` (reuse the
  ADR-336 `PiAdapter` — no parallel emission path).
- **R4** — `bin/cos-pi-guard`: thin wrapper (venv-aware) over the gate.
- **R5** — `examples/pi-extension/cos-bridge.ts`: pi extension that on
  `tool_call` spawns the guard with the event JSON and returns its `{block,
  reason}`; on `session_start` notifies. Mirrors `damage-control.ts` API exactly.
- **R6** — `examples/pi-extension/README.md`: install + manual smoke-test recipe.
- **R7** — Fail-open on gate error: if the guard crashes/times out, the shim must
  NOT block pi (observability must never brick the agent) — but it logs the fault.

## Acceptance Criteria

1. `echo '{"tool":"write","input":{"path":".env"}}' | python3 scripts/pi_tool_gate.py`
   → `block: true`, reason mentions the blocked path. (`jq .block` = `true`)
2. `echo '{"tool":"bash","input":{"command":"rm -rf /"}}' | … gate` → `block: true`.
3. `echo '{"tool":"read","input":{"path":"src/app.ts"}}' | … gate` → `block: false`.
4. Every gate call emits exactly one canonical event; `canonical-events.jsonl`
   contains a `tool_use_start` with the right `tool_name`.
5. `pytest tests/unit/test_pi_tool_gate.py` passes (≥6 cases incl. block/allow/emit).
6. The shim↔gate contract is tested: the exact JSON `cos-bridge.ts` sends is
   accepted by the gate and yields a valid decision.
7. No regression: control-plane `hook-fast` audit = 0 blocks; harness adapter
   tests still pass.

## Technical Approach

- Reuse `AgentPermissionManager.ALWAYS_BLOCKED` (import) + `fnmatch` for path policy.
- Destructive-command policy: a small curated regex set aligned with
  `hooks/destructive-rm-blocker.sh` / `destructive-git-blocker.sh` intent (not a
  reimplementation of all 152 hooks — a focused, high-signal subset; deeper hook
  reuse is a documented follow-up).
- Live event: build `{"type":"message","message":{"role":"assistant",
  "content":[{"type":"toolCall","id":…,"name":tool,"arguments":input}], …}}` and
  call `dispatch_event(...)`.
- TS shim: `child_process.spawnSync("bin/cos-pi-guard", …, {input: JSON})`,
  parse stdout; on any error return `{block:false}` (R7 fail-open).

## Out of Scope (documented follow-ups)

- Full reuse of all COS blocking hooks inside pi (this MVP is a high-signal subset).
- A Go provider for pi (`internal/provider/pi.go`).
- Live end-to-end validation in pi (requires installing the extension + an authed
  pi run in the operator's environment) — the recipe is provided in the README.
