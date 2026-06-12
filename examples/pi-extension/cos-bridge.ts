// cos-bridge — pi extension that puts the Cognitive OS *inside* pi (ADR-336, Vector D).
//
// On every pi tool call this shim shells out to the COS guard (bin/cos-pi-guard),
// which (1) emits a live canonical event (ADR-033 PiAdapter) and (2) returns a
// governance decision. If the COS says block, the tool call is aborted — the same
// role Claude Code's PreToolUse hooks play. This is the in-process counterpart to
// the post-hoc transcript adapter: it moves pi from "observed from outside" to
// "governed from inside".
//
// The API surface (pi.on("tool_call") => {block, reason}, ctx.abort, ctx.ui) is the
// same one pi's own damage-control.ts extension uses, so behaviour is well-grounded.
//
// Install: see ./README.md. Enable governance by setting COS_PI_GUARD (absolute
// path to bin/cos-pi-guard) or COS_HOME (the COS install root).
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { spawnSync } from "child_process";

function guardPath(): string | null {
	if (process.env.COS_PI_GUARD) return process.env.COS_PI_GUARD;
	if (process.env.COS_HOME) return `${process.env.COS_HOME.replace(/\/$/, "")}/bin/cos-pi-guard`;
	return null;
}

export default function (pi: ExtensionAPI) {
	const guard = guardPath();

	pi.on("session_start", async (_event, ctx) => {
		if (guard) {
			ctx.ui.notify(`🧠 COS bridge active → ${guard}`);
			ctx.ui.setStatus("🧠 COS governance: ON");
		} else {
			ctx.ui.notify("🧠 COS bridge: set COS_PI_GUARD or COS_HOME to enable governance");
			ctx.ui.setStatus("🧠 COS governance: OFF (telemetry only)");
		}
	});

	pi.on("tool_call", async (event, ctx) => {
		if (!guard) return { block: false }; // not configured → no-op
		const descriptor = JSON.stringify({
			tool: event.toolName,
			input: event.input,
			cwd: ctx.cwd,
		});
		try {
			const res = spawnSync(guard, [], { input: descriptor, encoding: "utf8", timeout: 5000 });
			// Fail-open: any non-zero / empty / unparseable response must NOT brick pi.
			if (res.status !== 0 || !res.stdout) return { block: false };
			const decision = JSON.parse(res.stdout.trim()) as { block?: boolean; reason?: string };
			if (decision.block) {
				const reason = decision.reason || "policy violation";
				ctx.ui.notify(`🛑 COS blocked ${event.toolName}: ${reason}`);
				ctx.ui.setStatus(`⚠️ COS blocked: ${reason.slice(0, 30)}...`);
				ctx.abort();
				return {
					block: true,
					reason: `🛑 BLOCKED by Cognitive OS: ${reason}\n\nDo not attempt to work around this restriction. Report it to the user exactly as stated and ask how to proceed.`,
				};
			}
		} catch {
			// Gate crash / timeout → fail open (observability must never block the agent).
			return { block: false };
		}
		return { block: false };
	});

	// Live tool_use_end: emit a correlated end event after each tool runs.
	pi.on("tool_result", async (event, ctx) => {
		if (!guard) return;
		const descriptor = JSON.stringify({
			phase: "result",
			tool: event.toolName,
			id: event.toolCallId,
			is_error: event.isError,
			cwd: ctx.cwd,
		});
		try {
			// Fire-and-forget telemetry — must never affect pi.
			spawnSync(guard, [], { input: descriptor, encoding: "utf8", timeout: 5000 });
		} catch {
			/* ignore telemetry faults */
		}
	});
}
