# xplan

Interactive deep research + planning + execution framework for new projects. Interviews you upfront, researches deeply, proposes tech stack and scope for your sign-off, creates a parallelized execution plan with peer review, and executes via parallel agents.

## What This Module Does

xplan is a human-in-the-loop planning framework with mandatory confirmation gates throughout:

- **Phase 0** - Parse input, create plan directory
- **Phase 0.5** - Discovery interview: confirm core concept, choose research depth
- **Phase 1** - Deep research via parallel agents (configurable preset: Full / Technical Only / Market & Product / Lite / Custom)
- **Phase 1.5** - Research review with business viability assessment; confirm to proceed
- **Phase 2** - Naming ideation (optional, with domain availability checks)
- **Phase 2.5** - Tech stack sign-off: propose stack, get approval
- **Phase 2.6** - Scope sign-off: approve epic structure and wave breakdown
- **Phase 2.7** - Multi-agent setup review
- **Phase 3** - Create parallelized plan with epics and dependency waves
- **Phase 4** - Peer review by security, architecture, and business logic agents
- **Phase 5** - Write comprehensive plan.md
- **Phase 6** - Final confirmation gate before execution
- **Phase 7** - Create repo, issues, and spawn parallel agents per wave
- **Phase 8** - Verification, audit, retrospective, optional template generation

**`--light` flag**: Skips Phases 0.5, 1.5, 2.5, 2.6, and 2.7. Uses minimal clarification + traditional section-by-section walkthrough instead of the interview-driven flow. Equivalent to old xplan behavior.

Companion commands:
- **/xplan-status** - Check progress on a running or completed plan
- **/xplan-resume** - Resume an interrupted plan execution from its last checkpoint

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/xplan.md` | command | Main planning and execution command (/xplan) |
| `commands/xplan-status.md` | command | Plan progress dashboard (/xplan-status) |
| `commands/xplan-resume.md` | command | Resume interrupted execution (/xplan-resume) |

## Dependencies

- **multi-agent**: Required for parallel agent execution during research, review, and implementation phases
- **[lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch)** (companion install): xplan's Phase 1 delegates research to the `/deepresearch` command, which is not part of CCGM - it lives in a standalone repo with its own installer

### /deepresearch - required for research phase

xplan's research phase (Phase 1) spawns an agent that runs `/deepresearch` to produce a comprehensive research.md. Without it, xplan cannot complete its research step.

`/deepresearch` uses a local pipeline - Ollama (qwen2.5:72b) for query generation and fact extraction, SearXNG (self-hosted Docker) for web search, and a single Anthropic API call (Sonnet) for synthesis. It requires Docker, Ollama (~40GB model), and a Python venv, which the installer handles.

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
cp commands/xplan-status.md ~/.claude/commands/xplan-status.md
cp commands/xplan-resume.md ~/.claude/commands/xplan-resume.md
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

After installation, invoke with `/xplan <project concept or idea>`, `/xplan <idea> --repo <existing-repo-path>`, or `/xplan <idea> --light` to skip interactive interview phases.
