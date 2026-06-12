# ADW Patterns — AI Developer Workflows

> Source: "Tactical Agentic Coding" by IndyDevDan (agenticengineer.com)

## What is an ADW?

An AI Developer Workflow (ADW) combines **deterministic code** (pipelines, scripts, CI steps) with **non-deterministic agents** (LLM-powered decision-making and code generation). The deterministic layer provides structure and repeatability; the agent layer provides intelligence and adaptability.

```
ADW = Deterministic Pipeline + Non-Deterministic Agents
```

### Key Properties

- **Repeatable**: Same trigger produces consistent workflow structure
- **Measurable**: Each step has metrics (duration, cost, success rate)
- **Optimizable**: Metrics drive improvements to both pipeline and agent steps
- **Composable**: ADWs can embed other ADWs or share steps

## Cognitive OS as ADW Implementation

The production ADW in Cognitive OS is the **skill-driven SDD pipeline** — a
deterministic 8-phase DAG whose phase work is executed by non-deterministic
agents loading SDD skills, governed by the hook mesh.

> **Historical note (documentation-truth, ADR-277):** an earlier generation of
> this doc described a standalone workflow-YAML engine — per-pipeline YAML
> files under a `.cognitive-os/workflows/` root with `agent`/`script`/`gate`
> step types, executed by a dedicated pipeline-executor module. That engine
> was **removed 2026-04-20 with 0 production callers** (see the deprecation
> note at the top of `packages/agent-lifecycle/lib/batch_runner.py`). Do not
> author workflow YAMLs against that schema; it has no runtime.

### The Real Mechanism

| Component | Location | Role |
|-----------|----------|------|
| Phase DAG + resume | `packages/sdd-compound/lib/sdd_resume.py` | Deterministic 8-phase order, dependency gating, state resume |
| Batch runner | `packages/agent-lifecycle/lib/batch_runner.py` | Runs SDD phases for one or many changes (CLI or YAML batch file) |
| Phase skills | `skills/sdd-spec`, `skills/sdd-tasks`, `skills/sdd-apply`, `skills/sdd-verify` | Non-deterministic agent steps, one skill per phase |
| Issue pipeline | `skills/issue-pipeline` (→ `packages/sdd-compound/skills/issue-pipeline`) | End-to-end issue → SDD lane composition |
| Consumer lane | `cos sdd` (Go CLI, `cmd/cos/internal/cli/sdd.go`) | Writes durable phase artifacts under `.cognitive-os/workflows/sdd/<feature>/` |
| Governance | Hook mesh (PreToolUse/PostToolUse/Stop) | Gates, trust report, blast radius, rate limits around every agent step |

### The 8 Phases

```
explore → propose → spec → design → tasks → apply → verify → archive
```

Phase order and dependencies are enforced in code
(`SDD_PHASES` + `PHASE_DEPENDENCIES` in `packages/sdd-compound/lib/sdd_resume.py`).
A phase cannot start until its dependencies are complete; state is persisted so
interrupted runs resume from the last completed phase.

### Artifact Layout (consumer lane)

`cos sdd` creates `.cognitive-os/workflows/sdd/` **on demand** — the directory
does not exist until the first SDD run, and its absence is not an installation
defect:

```
.cognitive-os/workflows/sdd/state.json
.cognitive-os/workflows/sdd/<feature>/requirements.md
.cognitive-os/workflows/sdd/<feature>/design.md
.cognitive-os/workflows/sdd/<feature>/tasks.md
.cognitive-os/workflows/sdd/<feature>/traceability.md
.cognitive-os/workflows/sdd/<feature>/review.md
```

## ADW Lifecycle

### 1. Design

Define the pipeline steps, their dependencies, and success criteria.

```
Trigger → Step 1 → Gate → Step 2 → Step 3 → Gate → Output
                     |                         |
                     v                         v
                  (abort)                   (retry)
```

Questions to answer:
- What triggers this workflow?
- What are the mandatory steps vs optional?
- What gates prevent bad outputs from flowing downstream?
- What is the maximum budget (tokens, time, cost)?

### 2. Test

Validate the pipeline with controlled inputs before deploying.

- Run with a known task that has a known-good outcome
- Verify each step produces expected artifacts
- Verify gates correctly block bad inputs
- Measure baseline metrics (duration, cost, token usage)

### 3. Deploy

Make the pipeline available for use.

- Implement phase logic as a skill (see `skills/sdd-apply` for the pattern)
- Wire deterministic ordering through the DAG (`sdd_resume.py`) or the batch
  runner rather than a bespoke executor
- Add entry to CATALOG.md if user-invocable
- Document trigger mechanism (command, event, schedule)

### 4. Monitor

Track pipeline performance over time.

- skill-metrics.jsonl captures per-step data
- Agent KPIs aggregate pipeline-level metrics
- Error learning captures step failures

### 5. Optimize

Improve based on monitoring data.

- Model routing: downgrade model for steps that succeed with cheaper models
- Step consolidation: merge steps that always run together
- Gate tuning: adjust thresholds based on false positive/negative rates
- Budget adjustment: tighten or loosen per-step budgets

## Creating a New ADW

There is no workflow-YAML authoring path. To add a new ADW today:

1. **Express phases as skills** — one focused skill per agent step
   (`skills/<phase-skill>/SKILL.md`), following the existing SDD phase skills.
2. **Sequence deterministically** — for SDD-shaped work, reuse the 8-phase DAG
   via the batch runner; for other shapes, a thin script that invokes skills in
   order with explicit gates between them is the supported pattern.
3. **Gate with hooks** — the governance mesh (trust score, claim validation,
   blast radius, rate limits) fires automatically around every agent step; add
   bespoke gates as shell checks between steps, not as a new engine.
4. **Register** — CATALOG.md for user-invocable entry points; Engram topic keys
   for cross-session state.

## ADW Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| All-agent pipeline | No deterministic checkpoints, unpredictable | Add gates between agent steps |
| No budget limits | Cost can spiral on complex tasks | Set max_cost and max_duration |
| Missing success criteria | Cannot verify step completed correctly | Every agent step needs verification |
| Monolithic steps | One step does too much, hard to debug | Break into smaller, focused steps |
| No failure handling | Pipeline crashes on first error | Define on_failure for each step |
| Hardcoded models | Cannot optimize cost/quality tradeoff | Use model-routing table |
| Building a new engine | Duplicates the DAG + hooks substrate; dies with 0 callers | Compose skills + scripts + gates on the existing substrate |

## Relationship to Other Concepts

| Concept | Relationship |
|---------|-------------|
| PITER | PITER is an inner loop within ADW steps — it handles the implement/test/refine cycle |
| SDD | SDD is the production ADW in Cognitive OS — 8 phases with defined artifacts |
| Closed-loop prompts | Enable agent steps to self-correct within their execution |
| ZTE | ADWs are the execution mechanism for ZTE — event-triggered ADWs are Phase 2 |
| Leverage Point 10 | ADWs ARE leverage point 10 (workflow automation) |

## Execution Entry Points

```bash
# Consumer SDD lane (creates .cognitive-os/workflows/sdd/ on demand)
cos sdd

# Batch runner — one or many changes, all phases or a single phase
python3 packages/agent-lifecycle/lib/batch_runner.py --help

# In-session: skill-driven phases
# /sdd-apply, /sdd-verify (see skills/ and CATALOG.md)
```

State for the consumer lane lives at `.cognitive-os/workflows/sdd/state.json`;
the in-repo DAG persists resume state per change via `sdd_resume.py`.
