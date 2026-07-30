# xplan

Interactive deep research + planning + execution framework for new projects. Interviews you upfront, researches deeply, proposes tech stack and scope for your sign-off, creates a parallelized execution plan, hardens it with constructive peer review *and* a sequence of adversarial reviews (6 independent reviews in the full configuration), and executes via parallel agents.

## What This Module Does

xplan is a human-in-the-loop planning framework with mandatory confirmation gates throughout:

- **Phase 0** - Parse input, create plan directory
- **Phase 0.4** - Existing-repo analysis (only with `--repo`): a Source Freshness Guard fetches origin, pins the default-branch anchor SHA, and plans against a temp worktree at that anchor so a stale clone never poisons the plan. Skipped for greenfield.
- **Phase 0.5** - Discovery interview: confirm core concept, choose research depth
- **Phase 1** - Deep research via parallel agents (configurable preset: Full / Technical Only / Market & Product / Lite / Custom)
- **Phase 1.5** - Research review with business viability assessment; confirm to proceed
- **Phase 2** - Naming ideation (optional, with domain availability checks)
- **Phase 2.5** - Tech stack sign-off: propose stack, get approval
- **Phase 2.6** - Scope sign-off: approve epic structure and wave breakdown
- **Phase 2.7** - Multi-agent setup review
- **Phase 3** - Create parallelized plan with epics and dependency waves
- **Phase 4** - Constructive peer review by security, architecture, and business logic agents (stage 1 of 2)
- **Phase 5** - Write comprehensive plan.md (+ 5.6 self-review loop)
- **Phase 5.7** - Adversarial review sequence (stage 2 of 2): **3 sequential `adrev-reviewer` passes** on Opus 4.8 (max effort). Each pass attacks the plan *after* the previous pass's fixes are incorporated (it uses the agent's native apply mode), so only one reviewer edits `plan.md` at a time and the third pass judges the fully-hardened plan. A finished plan has had **6 independent reviews in the full configuration** (3 standard + 3 adversarial).
- **Phase 6** - Web review (default surface) + final confirmation gate before execution
- **Phase 7** - Create repo, issues, and spawn parallel agents per wave
- **Phase 8** - Verification, audit, retrospective, optional template generation

### Three Modes

| Mode | Interview | Research | Tech Stack | Scope | Reviews | Walkthrough |
|------|-----------|----------|------------|-------|---------|-------------|
| Default (interactive) | Full Q&A | Full | Approved by user | Approved by user | Standard + **adversarial sequence** | Skipped (approved inline) |
| `--light` | Skipped | Reduced (inferred) | Internal default | Internal | Optional (no adversarial sequence) | Full section-by-section at end |
| `--autonomous` (or `/xplana`) | Skipped | **Full** | Internal (best-fit) | Internal (best-fit) | **Full standard + adversarial sequence (always)** | Plan-as-artifact presentation at end |

Reviews run in two stages: Phase 4 standard peer review against the draft, then the Phase 5.7 adversarial sequence (3 sequential passes) against the finished plan. A completed plan has survived **6 independent reviews in the full configuration** (3 standard + 3 adversarial).

### Autonomous-Execution Tenets

Every plan carries four requirements that let it execute with minimal human involvement and self-certify — written during planning (Phase 3), verified by the self-review (Phase 5.6), and enforced by the adversarial reviewer (Phase 5.7 / `adrev-reviewer` tenets T1–T4), which expands the plan when any is thin:

1. **Human work at the edges** (T1) — human involvement is minimized (anything an agent can do via CLI/API is not human work) and what remains is bucketed to the start (front-loaded prerequisites) or the end (deferred steps), never mid-run. Once execution starts, it does not pause for a person.
2. **Follow-up-completion contract** (T2, plan §9.5) — any follow-on work discovered during execution is tracked, triaged, and — if in-scope — completed before execution is reported complete. Only genuinely human-blocked work may remain open. Phase 7 gates completion on it.
3. **Autonomous decision context** (T3, plan §1.4) — the plan carries the software's mission, the codebase's governing conventions, and its decision principles, so an execution agent directs unplanned follow-on work itself instead of stopping to ask. `/etp` reads this context (its Phase 1.5) to triage and reason.
4. **Comprehensive autonomous E2E testing** (T4, plan §8) — every plan ships a full autonomous E2E suite over all testable surfaces, wired into CI as a blocking merge gate, so the suite (not the user) is the ready-to-merge oracle and no manual testing is required. New projects build it in from the ground up (a Wave-1 harness epic); existing repos get optimistic gap-fill for any touched area lacking coverage. The plan provisions whatever infra certainty needs (testing agents, RunPod, cloud Mac, real devices) — no resource constraint on testing. Phase 7 and `/etp` gate completion on a green suite.

### Live-Testing Authorization (plan §8.6)

Live testing — app launches/relaunches, dictation firing, synthetic input events, focus changes, machine-global input/audio overrides, mic/camera capture, host-driven simulator or device runs — never runs on the dev machine, whose input surface is the user's control channel to every concurrent agent stream (`live-testing-guard` module).

Planning asks where it runs and whether the user approves it (Phase 0.5.2 Q8, deferred to Phase 3.3.5 in `--light`), and records the answer in **plan §8.6** with the runner named and the grant dated. `--autonomous` cannot answer for the user: it writes `NOT AUTHORIZED` and surfaces the affected steps at the 6.A walkthrough and the 6.5 gate. Execution (`/etp` Phase 0.6, `/xplan-resume` §3.5, `/xplan` Phase 7.2) holds every live-testing step whose grant is missing, incomplete, or names a different machine, surfaces it by name, and asks — while the rest of the run continues. A plan step instructing a live test is never its own authorization.

**`--light`**: fast path. Reduced depth, minimal interaction. Skips Phases 0.5, 1.5, 2.5, 2.6, and 2.7 (Q8 is deferred to 3.3.5, not dropped). Traditional section-by-section walkthrough at the end.

**`--autonomous`**: deep path. Maximum depth, zero interruption until the final gate. Runs the full research pipeline (all 7 agents), full standard review (security + architecture + business logic), the self-review loop, and the Phase 5.7 adversarial review sequence (3 sequential `adrev-reviewer` passes on Opus 4.8 at max effort, each incorporating its fixes before the next; the third judges the fully-hardened plan). Tech stack, scope, naming, and multi-agent setup are inferred and documented in `decisions.md`. At Phase 6 the completed plan is presented as a single structured artifact with every inferred default called out, then the (non-bypassable) Phase 6.5 final execution gate fires. Pick this when you know exactly what you want to plan and prefer reviewing a finished artifact over answering questions during creation. Correct any wrong inferences with `/xplan --deepen ~/code/plans/{concept-name}` rather than re-running from scratch.

`--light` and `--autonomous` are mutually exclusive.

### Web Review (Phase 6)

Phase 6's default review surface is a local browser UI served by stdlib `http.server` on 127.0.0.1. xplan renders `plan.md` with `marked.js` (CDN) and attaches a comment button to every `##` and `###` heading. The user can:

- **Submit for deepening** — xplan reads the comments, runs a targeted Deepen Mode pass on each commented section, re-renders the patched plan for a second review round, then proceeds to the Phase 6.5 gate.
- **Accept as-is** — proceed directly to the Phase 6.5 gate.

The web UI activates when `plan.md` exists and the environment is not headless. Fallbacks to the terminal walkthrough (6.A / 6.1-6.4) when:
- `XPLAN_NO_WEB=1` is set
- No `$DISPLAY` on Linux
- The server cannot bind a loopback port
- The helper script `~/.claude/lib/xplan-web-review.py` is missing

The Phase 6.5 final execution gate always fires afterward, web or not. The web UI is the review mechanism; 6.5 is the go/no-go.

Comments are persisted to `~/code/plans/{concept-name}/comments.json` before the server shuts down — safe to close the tab or CTRL+C the script after clicking Submit.

Companion commands:
- **/xplana** - Thin alias for `/xplan --autonomous`
- **/xplan-status** - Check progress on a running or completed plan
- **/xplan-resume** - Resume an interrupted plan execution from its last checkpoint
- **/etp** - Execute ready work end-to-end — a plan file (xplan-authored or hand-written) *or* one-or-more investigated GitHub issues. Parallel implementation agents, full two-stage adversarial review of every PR by a *separate* agent, reasonable-and-valid fixes, follow-up completion, run-to-completion. Stops only for absolute blockers, which it reports while continuing all non-blocked work.

### /etp vs /xplan-resume

Both execute work, but they are not interchangeable. `/xplan-resume` resumes an `/xplan`-native interrupted run using xplan's epic/wave checkpoint structure - it is xplan-specific. `/etp` is the general-purpose execution engine: point it at any plan file, a single issue (`/etp #42`), or a batch (`/etp #42 #43`) - it resolves the target into units, decomposes, executes, adversarially reviews, and completes, including the follow-up work that surfaces mid-run. Ceremony scales to the work: a single issue skips the wave/clone machinery a plan needs. `/etp` is resumable - a plan run checkpoints beside the plan, an issue/batch run reconciles against live GitHub state - so a re-invocation continues rather than restarts.

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/xplan.md` | command | Main planning and execution command (/xplan) |
| `commands/xplana.md` | command | Autonomous alias - /xplana invokes /xplan --autonomous |
| `commands/xplan-status.md` | command | Plan progress dashboard (/xplan-status) |
| `commands/xplan-resume.md` | command | Resume interrupted execution (/xplan-resume) |
| `commands/etp.md` | command | Execute a plan or GitHub issue(s) end-to-end with adversarial PR review and follow-up completion (/etp) |
| `lib/xplan-status-gather.sh` | lib | Helper script that gathers plan progress data for /xplan-status |
| `lib/xplan-web-review.py` | lib | Local web server that renders plan.md in browser with section-level comment support for Phase 6 review |

## Dependencies

- **multi-agent**: Required for parallel agent execution during research, review, and implementation phases
- **adversarial-review**: Provides the `adrev-reviewer` agent that Phase 5.7's adversarial review sequence dispatches (3 sequential passes on Opus 4.8). Installed automatically as a module dependency.
- **[lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch)** (companion install): xplan's Phase 1 delegates research to the `/deepresearch` command, which is not part of CCGM - it lives in a standalone repo with its own installer

### /deepresearch - required for research phase

xplan's research phase (Phase 1) spawns an agent that runs `/deepresearch` to produce a comprehensive research.md. Without it, xplan cannot complete its research step.

`/deepresearch` uses a fully local pipeline - Ollama (qwen2.5:72b) for query generation and fact extraction, SearXNG (self-hosted Docker) for web search - then Claude Code synthesizes the results. No external API keys required. It requires Docker, Ollama (~40GB model), and a Python venv, which the installer handles.

```bash
git clone https://github.com/lucasmccomb/lem-deepresearch.git
cd lem-deepresearch
./install.sh
```

See the [lem-deepresearch README](https://github.com/lucasmccomb/lem-deepresearch) for manual setup, prerequisites, and troubleshooting.

## Manual Installation

```bash
# Copy command files
mkdir -p ~/.claude/commands
cp commands/xplan.md ~/.claude/commands/xplan.md
cp commands/xplana.md ~/.claude/commands/xplana.md
cp commands/xplan-status.md ~/.claude/commands/xplan-status.md
cp commands/xplan-resume.md ~/.claude/commands/xplan-resume.md
cp commands/etp.md ~/.claude/commands/etp.md

# Copy lib files
mkdir -p ~/.claude/lib
cp lib/xplan-status-gather.sh ~/.claude/lib/xplan-status-gather.sh
cp lib/xplan-web-review.py ~/.claude/lib/xplan-web-review.py
chmod +x ~/.claude/lib/xplan-web-review.py
```

### Plans Directory

xplan creates plan directories under `~/code/plans/`. Create this directory if it does not exist:

```bash
mkdir -p ~/code/plans
```

Optional: Create a templates directory for reusable plan patterns:

```bash
mkdir -p ~/code/plans/_templates
```

After installation, invoke with:
- `/xplan <concept>` - full interactive mode
- `/xplan <concept> --repo <existing-repo-path>` - plan work against an existing repo
- `/xplan <concept> --light` - fast path, minimal interaction
- `/xplan <concept> --autonomous` or `/xplana <concept>` - full-depth pipeline with zero mid-flow prompts; completed plan presented at the end
- `/etp <plan-file-or-dir | #issue …>` - execute a plan or investigated GitHub issue(s) end-to-end; `/etp #42 #43` batches independent issues (`--dry-run` to preview, `--confirm` for a go/no-go gate, `--max-agents N` to cap parallelism, `--light-review` to opt out of Stage 2 on trivial diffs)
