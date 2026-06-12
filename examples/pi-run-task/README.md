# Driving the `pi` agent with `cos run-task` (ADR-336)

This example wires the **pi** coding agent (`@earendil-works/pi-coding-agent`) into
the Cognitive OS's headless task runtime. `cos run-task` provides the isolated
git worktree, acceptance gating, and trust-report; `pi` is the agent that makes
the change. No Go changes are needed — `cos run-task` runs any
`execution.command` via `/bin/sh -c` inside the worktree.

## Pieces

| Piece | Role |
|-------|------|
| [`bin/cos-pi-agent`](../../bin/cos-pi-agent) | Gateway: builds and execs `pi -p --mode json` with a persona from `.pi/agents/<role>.md`. Reads the task from `COS_TASK_DESCRIPTION`. |
| [`pi-task.json`](./pi-task.json) | A `cos run-task` payload pointing `execution.command` at the gateway. |
| [`bin/cos-pi-ingest`](../../bin/cos-pi-ingest) | Replays the resulting pi session transcript into the canonical event stream (ADR-033 PiAdapter). |

## Verify the wiring (no pi auth / no token cost)

`COS_PI_DRYRUN=1` makes the gateway print the exact `pi` command it would run and
exit 0, so you can prove the whole `cos run-task` chain end-to-end without
invoking pi:

```bash
COS_PI_DRYRUN=1 bin/cos-pi-agent --role builder --task "add a CHANGELOG entry"
# → DRYRUN cos-pi-agent role=builder role_file=/.../.pi/agents/builder.md
#   pi -p --mode json --no-session --append-system-prompt /.../builder.md add\ a\ CHANGELOG\ entry
```

## Run for real

1. Edit `description` and `acceptance_criteria` in `pi-task.json`.
2. Authenticate pi once (`pi` uses your provider creds; e.g. run `claude` to seed
   Claude credentials, or set `COS_PI_PROVIDER`/`COS_PI_MODEL`).
3. Run:

```bash
cos run-task --payload examples/pi-run-task/pi-task.json --workspace /path/to/repo
```

`cos run-task` writes `payload`, `preflight`, `execution`, `acceptance`, `diff`,
`outcome`, and `trust-report` artifacts under the payload's `artifacts.dir`.

4. Fold the run's telemetry into the canonical stream:

```bash
bin/cos-pi-ingest --json
```

## Config knobs (env)

| Env | Default | Meaning |
|-----|---------|---------|
| `COS_PI_ROLE` | `builder` | persona file `.pi/agents/<role>.md` (planner, builder, reviewer, …) |
| `COS_PI_AGENTS_DIR` | `~/github/.pi/agents` → `./.pi/agents` | where personas live |
| `COS_PI_PROVIDER` / `COS_PI_MODEL` | pi defaults | pass through to `pi --provider/--model` |
| `COS_PI_DRYRUN` | `0` | `1` = print the command, do not run pi |
