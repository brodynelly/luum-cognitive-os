# Agentic / ADW Layer Audit & Recommendation — 2026-06-11

**Question asked:** Is the `luum-cognitive-os` (COS) approach a good way to add an "agentic
layer" to my codebases, and how does it rank for **ADW** (AI Developer Workflow) implementations?

**Scope audited:**
- `luum-cognitive-os` — the Cognitive OS (deep audit)
- `.pi` — the **pi** coding-agent harness ("PyCoding Agent" = pi agents)
- `claude-code-plugins` — the `bnelly-claude-software` plugin marketplace (35 plugins)
- `tac-4` — the Principled-AI-Coding ADW reference implementation (gold standard)
- `UGC-manager` — the target repo for an agentic layer

**Method:** 4 parallel evidence-cited audit agents (every claim cites a file path) + independent
verification of the 3 load-bearing claims. Native Claude `Agent` tool (not the COS Qwen dispatcher).

> **Scope & boundary (clean-room, conceptual-only).** This is a **conceptual-only** architecture
> analysis of the operator's own repositories and already-installed tooling. Where it discusses
> third-party or proprietary/unlicensed components (the `pi` agent harness, the `tac` course
> material, the `tac-4` demo), the treatment is **clean-room** with **no reuse**: **no code, assets,
> prompts, or schemas are copied, ported, or vendored**. Words like "reusable", "adopt", and "graft"
> below mean *invoke the operator's own installed, licensed plugins as-is and re-implement patterns
> natively* — **do not copy, do not port, do not vendor** any third-party source, and treat none of
> these as a vendored reference implementation to clone.

---

## TL;DR — the headline

**Porting the COS wholesale onto another codebase is the wrong move.** The COS is a *governance
operating system*, not a portable agentic layer. Its genuinely-working part is hook governance +
SDD spec discipline; its **automated ADW core is dormant** (the orchestrator/dispatch path has
never executed — `llm-dispatch.jsonl` does not exist). It is coupled to Python/Bash/Go, 250+ hooks,
Engram, and a symlink-farm `lib/`. Lift-and-shift cost is enormous and most of it is COS
self-governance, not app value.

**You do not need to.** `UGC-manager` **already has the right agentic layer** — a faithful
`tac-4`-style ADW (scored **88/100**), higher than the COS's own ADW component (**42/100**). The
work there is not "add the COS"; it's **commit + harden what already exists**, then **graft 3–4
high-value COS patterns** (selected hooks, SDD/EAS spec discipline, JSONL observability).

**Best reusable substrate going forward: the `tac` plugin** — language-agnostic (auto-detects
`package.json`), full plan→build→review→fix→ship loop, worktrees, issue classification, KPIs.

---

## Ranking — ADW substrate options (best → worst for your case)

| # | Approach | ADW maturity | Portability to JS/TS | Weight / onboarding cost | Verdict |
|---|----------|--------------|----------------------|--------------------------|---------|
| **1** | **`tac` plugin / `tac-4` pattern** (already in UGC-manager) | Gold reference (~95) | Native — detects `package.json` | Light | **Adopt & standardize** |
| **2** | **Cherry-picked COS patterns** (hooks, SDD+EAS, JSONL telemetry, trust-report) | High-value slices | Medium (reimplement in JS/Python) | Medium | **Graft selectively** |
| **3** | **`pi` agents** (planner/builder/reviewer chains) | Low (4/10) | Portable harness (reads `.claude/agents/`) | Light | **Aux — cheap 2nd opinion / interactive** |
| **4** | **Full COS port** | Dormant core (42) | Very poor (Py/Bash/Go-coupled) | Very heavy | **Avoid** |

**Maturity scoreboard (vs. tac-4 gold standard):**
`tac-4`/`tac` plugin ≈ **95** · **UGC-manager 88** · **COS 58** (ADW component **42**) · **pi ≈ 40**.

---

## 0. Defect found & fixed during the audit (broken-window)

The COS's own `control-plane-audit` PreToolUse hook **blocked every `Agent` launch** because
`scripts/agent-orchestration-boundary-audit.py` crashed with `NameError: name 'sys' is not defined`
(line 27 used bare `sys.path` while the module imported `sys as _cos_sys`; a prior bad edit had also
spilled an `import sys` line into the docstring). A crashed audit is treated as a hard BLOCK.

**Fixed in-session:** pointed lines 27–28 at the existing alias and restored the docstring. Verified:
`python3 scripts/agent-orchestration-boundary-audit.py --json` → `rc=0, status=pass`; control-plane
`hook-fast` lane → **0 blocks across 6 audits**. The whole agentic layer was gated by a one-line bug.

---

## 1. COS (luum-cognitive-os) ADW audit — **58/100, Class 2**

| Component | Score | Evidence |
|-----------|-------|----------|
| commands / skills | 82 | 190 skills (74 real + 113 symlinked from `packages/*/skills/`); complete SDD set (`skills/sdd-apply/SKILL.md`) |
| specs / plans | 78 | 8-phase SDD DAG `packages/sdd-compound/lib/sdd_resume.py`; **EAS** acceptance traceability (`REQ-*`/`AC-*`) — a genuine differentiator. Only 2 real SDD change dirs → low usage |
| **ADW / orchestration** | **42** | `lib/pipeline_executor.py` **removed**; `.cognitive-os/workflows/` **NOT FOUND** (but `adw-patterns.md` claims it exists); `workflows/*.py` **DEPRECATED**; `lib/issue_pipeline.py` **ORPHAN**; `scripts/orchestrator.py`+`lib/dispatch.py` real but never executed |
| **hooks (governance)** | **88** | **Strongest.** 254 hook scripts; 152 wired in `.claude/settings.json` across 10 lifecycle events; real enforcement (`hooks/orchestrator-skill-invocation-gate.sh`, `hooks/rate-limiter.sh`). Repo's own `reality-audit.md`: ~52% never fire |
| observability | 60 | Live JSONL streams (`agent-heartbeat`, `agent-trajectory`, `hook-timing`) but the cost/dispatch stream `llm-dispatch.jsonl` is **absent** |
| worktrees | 45 | Tooling exists (`scripts/cos-worktree-triage.sh`, `lib/worktree_audit.py`) but `git worktree list` shows only main — supported, not in active multi-agent use |

**ADW loop status: DORMANT.** The skill-driven, human-in-the-loop SDD slice is **REAL** (8-phase DAG
+ `skills/sdd-apply` + `skills/sdd-verify` + `lib/code_reviewer.py`, governed by 152 hooks). The
*automated* orchestrator/dispatch slice is **DORMANT** — strongest evidence: `scripts/orchestrator.py`
+ `lib/dispatch.py` define a complete Qwen→Claude cascade that writes `llm-dispatch.jsonl` on every
dispatch, **and that file does not exist** (only `dispatch-gate.jsonl`). The working loop runs through
Claude Code's **native** Agent tool, which ADR-049 itself notes "cannot be redirected."

**Top strengths (portable):** (1) dense real hook governance; (2) SDD + EAS spec→verify contract;
(3) intellectual honesty — ships its own `reality-audit.md` + ORPHAN/DEPRECATED markers;
(4) thoughtful multi-provider cost design (ADR-049); (5) rich JSONL observability substrate.

**Top gaps/risks (for reuse):** (1) doc-to-reality drift (`adw-patterns.md` cites phantom
artifacts); (2) extreme heaviness/coupling — it's an OS, not a layer; (3) automated ADW core is
dormant + bound to the proprietary native Agent tool; (4) Python/Bash/Go toolchain coupling
(snake_case audits, `go vet`, pytest lanes — not JS/TS-shaped); (5) governance overhead vs.
throughput (2 SDD changes, 0 dispatch events recorded).

**Portability verdict:** Lifting the whole COS onto a JS/TS app is hard and ill-advised. Cherry-pick
a dozen high-value `PreToolUse`/`Stop` hooks, the SDD 8-phase + EAS discipline, and the JSONL
observability convention — reimplemented natively — and ignore the dormant orchestrator/dispatch/
Engram/Valkey substrate.

---

## 2. pi agents + plugin marketplace

**pi (`.pi`) — ADW capability 4/10.** Standalone TUI agent (`@mariozechner/pi-coding-agent`) that
mirrors Claude conventions (reads `.claude/agents/*.md`). Roster:
`scout / planner / builder / reviewer / plan-reviewer / red-team / documenter / bowser` + a `pi-pi`
meta-expert set. Composition is pure YAML: `teams.yaml` (rosters) + `agent-chain.yaml` (linear
`$INPUT`-piped pipelines: `plan-build-review`, `scout-flow`, `plan-review-plan`, `full-review`).
Strong out-of-box `damage-control-rules.yaml` (blocks `rm -rf`, force-push, cloud-delete, SQL
`DROP`; `zeroAccessPaths` for secrets). **Limitations:** chains are linear/deterministic only — **no
fix-loop, no state gates, no worktrees, no ship/merge, no issue routing, no run observability**.
Good *interactive* multi-agent harness; thin *autonomous* ADW substrate. Multi-provider + local
Ollama is a plus.

**Plugins reusable for a JS/TS app (language-agnostic):**
- **`tac`** — THE ADW engine: 88 skills + 34 agents. `start-adw` (`plan_build`/`plan_build_review`/
  `plan_build_review_fix`), `orchestrate`, `scout-and-build`, `feature`/`bug`/`chore`/`patch`,
  `implement`, `test`/`test-e2e`, `resolve-failed-test`, `review`, `ship`, `classify-issue`,
  `generate-branch-name`, `pull-request`, `git-worktree-setup`, `track-kpis`, `agentic-layer-audit`,
  `multi-agent-observability`. `skills/test/SKILL.md` detects `package.json` **or** `pyproject.toml`
  → **JS/TS-ready as-is**.
- **`spec-driven-development`** — Spec-Kit 5-phase (constitution→specify→plan→tasks→implement) +
  EARS/Gherkin. The "front half" of an ADW.
- **`claude-code-observability`** — pure-Python harness hooks → JSONL audit trail (non-blocking).
- **`git`**, **`ci-cd`** (GitHub Actions), **`code-quality`** (review/security/debug agents — skip the
  `python` skill + dotnet markdown-lint hook), **`formal-specification`** (only the OpenAPI/state-
  machine slice).

**None of these plugins are coupled to the COS Python codebase.** Best off-the-shelf ADW substrate
for a JS/TS app = **the `tac` plugin**.

---

## 3. UGC-manager readiness — **88/100**

**Stack:** Node.js monorepo (JS, *not* TS at root) — Discord.js bot + web server (`src/`),
Vite+React onboarding (`onboarding/`), Express API (`onboarding-api/`), Capacitor iOS (`mobile/`).
No root `tsconfig.json`.

**Commands (verified):** Build `npm run build:onboarding` · Test `npm test`
(=`check`+`test:bot`+`test:api`, all `node --test` emitting TAP, exit-clean) · Typecheck
`npm run check` = `node --check` **syntax only (no tsc)** · **Lint MISSING** (no ESLint/Prettier).

**Already present (substantial TAC-style layer):**
- `.claude/commands/` — `bug`, `chore`, `implement`, `review`, `meta-prompt`, 5× `prime*`, plus
  `experts/` (5 domain experts with `expertise.yaml` + Act-Learn-Reuse prompts).
- `.claude/hooks/log_tool_event.py` (Pre/PostToolUse on `*`) → `agents/<run-id>/events.jsonl`;
  **mirrored across 3 harnesses** (`.claude/`, `.codex/`, `.pi/`).
- `adws/` — real Python orchestrator: `adw_modules/agent.py` shells `claude -p … --output-format
  json`, parses `is_error`/`exit_code`; `adw_chore_implement.py` is a plan→build→verify loop with
  `--validate`. Stdlib-only.
- `specs/` (~9 specs), `agents/<run-id>/{prompt,raw_output,result,events}` convention, `trees/` git
  worktree convention (active `trees/adw-2026-06-08-1`), `AGENTS.md` + `CLAUDE.md`, CI
  (`.github/workflows/onboarding.yml`).

**Leverage points:** standard-out=PARTIAL · tests=PRESENT · specs=PRESENT · commands=PRESENT ·
hooks=PRESENT · agent-outputs=PRESENT · worktrees=PARTIAL.

**Top 3 blockers:**
1. **The agentic layer is uncommitted** — `.claude/`, `.codex/`, `adws/`, `agents/`, `specs/experts/`,
   `AGENTS.md`, `CLAUDE.md` are all `??` untracked (verified). Worktrees off `main` and clean clones
   won't carry it. *Highest priority.*
2. **No real typecheck/lint** — `npm run check` is `node --check` syntax only; no `tsc`, no ESLint →
   the closed loop can catch crashes/smoke failures but not type/contract regressions.
3. **Thin verification at the bot/API core** — only 4 `node --test` files; `src/` logic is mostly
   syntax-checked, so an autonomous agent has weak ground-truth there.

---

## 4. ADW gold-standard checklist (from tac-4) + scorecard

The tac-4 pattern = **deterministic Python that shells out to a non-deterministic agent at each step,
captures structured output, and gates on success.**

| # | Ingredient (tac-4 path) | tac-4 | UGC-manager | COS |
|---|--------------------------|:----:|:-----------:|:---:|
| 1 | Gateway script — `adws/agent.py` | ✅ | ✅ `adws/adw_modules/agent.py` | ⚠️ orchestrator dormant |
| 2 | Deterministic orchestrator — `adws/adw_plan_build.py` | ✅ | ✅ `adw_chore_implement.py` | ⚠️ |
| 3 | Structured agent output (JSONL→typed) — `parse_jsonl_output()` | ✅ | ✅ `result.json` envelope | ✅ |
| 4 | Typed contracts — `adws/data_types.py` (Pydantic) | ✅ | ◐ `data_types.py` | ✅ |
| 5 | Machine-readable plan format — `.claude/commands/feature.md`→`specs/*.md` | ✅ | ✅ `specs/` + templates | ✅ SDD+EAS |
| 6 | Build primitive consuming a plan — `/implement` | ✅ | ✅ `.claude/commands/implement.md` | ✅ |
| 7 | Closed-loop validation gate — `adws/validate.py` (tests+build, non-zero) | ✅ | ◐ `npm test` (no tsc/lint) | ✅ staged |
| 8 | Issue→branch→commit→PR automation | ✅ | ◐ partial | ⚠️ |
| 9 | Standard-out / observability hooks | ✅ | ✅ `log_tool_event.py` | ✅ 152 hooks |
| 10 | Run-traceability ID — `make_adw_id()` | ✅ | ✅ `<run-id>` dirs | ✅ |
| 11 | Autonomous triggers — `trigger_cron.py`/`trigger_webhook.py` | ✅ | ❌ | ⚠️ webhook broken |
| 12 | Agent reference docs — `ai_docs/` | ✅ | ◐ AGENTS.md/CLAUDE.md | ✅ |

**Minimal viable ADW (must-haves):** gateway script · deterministic orchestrator · machine-readable
plan format · closed-loop validation command · issue→branch→PR. **UGC-manager has 4 of 5 solidly;
the weak link is #7 (validation depth) and #11 (autonomous triggers).**

---

## 5. Recommendation

**Is the COS a good approach to add an agentic layer to your codebases?**
**As a wholesale port — no.** As a *pattern library to harvest from — yes, selectively.* The COS's
real value is its **hook-governance discipline** and **SDD+EAS spec→verify contract**, not its
(dormant) orchestrator. The COS is best understood as your **R&D lab** for agentic patterns; the
**tac-4/tac-plugin ADW** is the **production substrate** you actually ship onto app repos.

**For UGC-manager specifically:** you've already built the right thing. Don't add the COS. Do this:

### Actionable plan

**Phase 1 — Make it durable (1 commit, ~15 min). _Unblocks everything._**
1. In `UGC-manager`: review then `git add` the agentic scaffold —
   `.claude/`, `.codex/`, `adws/`, `AGENTS.md`, `CLAUDE.md`, `specs/experts/`, and the `agents/`
   README/convention (keep run outputs gitignored). Fix the stale `.Codex/` path typo in `AGENTS.md`.
2. Commit: `chore: track agentic/ADW scaffold so worktrees inherit it`.
   *Acceptance:* `git ls-files | grep adws/` is non-empty; a fresh `git worktree add` under `trees/`
   contains `.claude/` and `adws/`.

**Phase 2 — Close the verification loop (~1–2 hrs). _Lifts the loop from "doesn't crash" to "behaves."_**
3. Add ESLint (flat config) + a `npm run lint` script; wire it into `npm test`.
4. Add `tsconfig.json` with `checkJs`/`allowJs` (or incremental `// @ts-check`) and a `npm run
   typecheck` (`tsc --noEmit`). Even loose typecheck beats `node --check`.
5. Add 2–3 behavior `node --test` cases around the Discord bot core (`src/`) and the Express API.
   *Acceptance:* `npm run lint && npm run typecheck && npm test` all exit 0 and emit machine-readable
   output an agent can parse.

**Phase 3 — Standardize on the tac plugin (~1 hr). _Replaces bespoke prompts with maintained ones._**
6. The `tac` plugin is already installed (v1.1.0). Point UGC-manager's loop at its primitives:
   `/tac:feature`/`/tac:bug`/`/tac:chore` to plan → `/tac:implement` → `/tac:test` →
   `/tac:resolve-failed-test` → `/tac:review` → `/tac:pull-request`. Keep your `adws/` orchestrator as
   the deterministic driver; have it call those skills instead of hand-rolled command markdown.
   *Acceptance:* one issue runs end-to-end plan→build→validate→PR from a `trees/` worktree.

**Phase 4 — Graft 3 COS patterns (selective, ~half day). _Highest-value COS borrowings._**
7. **Closed-loop validation gate** like `tac-4`'s `validate.py`: one script that runs
   `lint+typecheck+test+build`, emits `--json`, exits non-zero, and can comment back on the issue.
8. **JSONL observability convention** (you already have `events.jsonl`) + a tiny `cos-status`-style
   reader so runs are inspectable.
9. **A handful of governance hooks** (not 152): a secret/`.env` write-blocker, a destructive-bash
   guard (borrow pi's `damage-control-rules.yaml` regexes), and a "tests must pass before PR" Stop
   gate. Reimplement natively in `.claude/hooks/` — do **not** import the COS hook farm.

**Do NOT:** port `lib/dispatch.py`/`orchestrator.py`, Engram, Valkey, the symlink `lib/`, the SDD
package, or the 250-hook profile system into an app repo. That's COS-internal machinery.

---

## Appendix — verification evidence (run 2026-06-11)

```
[1] UGC-manager untracked agentic layer:
    git status --porcelain → ?? .claude/ ?? .codex/ ?? AGENTS.md ?? CLAUDE.md ?? adws/ ?? agents/ ?? specs/experts/
    git ls-files | grep -E 'adws/|^AGENTS.md|^\.claude/' → (empty)
[2] COS dispatch never ran:
    .cognitive-os/metrics/llm-dispatch.jsonl → No such file or directory
    .cognitive-os/metrics/dispatch-gate.jsonl → exists (1.5k)
[3] COS doc drift:
    .cognitive-os/workflows/ → No such file or directory (adw-patterns.md treats it as canonical)
[0] Fix verified:
    python3 scripts/agent-orchestration-boundary-audit.py --json → rc=0 status=pass
    scripts/cos-control-plane-audit --lane hook-fast → total blocks: 0 (6/6 pass)
```

**Open doc-truth item (COS):** `docs/08-References/root/adw-patterns.md` references
`.cognitive-os/workflows/` (and `pipeline_executor.py`) which do not exist. Per Rule 16 this should
land as a pointwise fix or a pending-truth ledger entry — flagged here, not yet actioned.
