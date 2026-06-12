# `cos-bridge` — governing pi from inside (ADR-336, Vector D)

This pi extension makes the Cognitive OS run **inside** pi. On every pi tool call
it shells out to the COS guard, which emits a **live** canonical event and returns
an allow/block decision. A block aborts the tool call — the in-process counterpart
to the post-hoc transcript adapter.

| Piece | Role | Verifiable here? |
|-------|------|------------------|
| [`scripts/pi_tool_gate.py`](../../scripts/pi_tool_gate.py) | the brain: governance decision + live event emission (reuses `PiAdapter`) | ✅ unit-tested |
| [`bin/cos-pi-guard`](../../bin/cos-pi-guard) | venv-aware wrapper, anchored to the COS install | ✅ |
| [`cos-bridge.ts`](./cos-bridge.ts) | thin pi extension: `tool_call` → guard → `{block,reason}` | ⚠️ needs live pi |

The TS shim mirrors the API of pi's own `damage-control.ts`
(`pi.on("tool_call", …) => { block, reason }`), which pi already runs — so its
behaviour is well-grounded even though the final end-to-end check happens in pi.

## Install

1. Make sure the gate works (no pi needed):

   ```bash
   echo '{"tool":"write","input":{"path":".env"}}' | bin/cos-pi-guard
   # → {"block": true, "reason": "COS: refuses to modify protected path (.env)", "event_emitted": true}
   ```

2. Point pi at the extension and tell it where the COS lives:

   ```bash
   export COS_HOME="$(git -C /path/to/luum-cognitive-os rev-parse --show-toplevel)"
   pi install /path/to/luum-cognitive-os/examples/pi-extension/cos-bridge.ts
   # or add the file under your .pi extensions and set COS_PI_GUARD=$COS_HOME/bin/cos-pi-guard
   ```

3. Run pi normally. On `session_start` it prints `🧠 COS governance: ON`. A blocked
   call shows `🛑 COS blocked <tool>: <reason>` and aborts.

## Manual smoke test (in pi)

Ask pi to `write` to `.env`, or run `rm -rf /` — the bridge blocks it and pi
reports the COS reason. Confirm a `tool_use_start` event landed in
`.cognitive-os/metrics/canonical-events.jsonl`.

## Fail-open guarantee

If the guard is unset, errors, or times out (5s), the bridge returns
`{block:false}` — observability must never brick the agent. Governance is additive
on top of pi's own `damage-control`.

## Scope

This is a high-signal policy subset (ALWAYS_BLOCKED paths + unmistakably
destructive commands), not a port of all 152 COS hooks. Broadening the gate to
reuse more COS blocking hooks is the documented follow-up.
