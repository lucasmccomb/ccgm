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
- **Phase 6** - Web review (default surface) + final confirmation gate before execution
- **Phase 7** - Create repo, issues, and spawn parallel agents per wave
- **Phase 8** - Verification, audit, retrospective, optional template generation

### Three Modes

| Mode | Interview | Research | Tech Stack | Scope | Reviews | Walkthrough |
|------|-----------|----------|------------|-------|---------|-------------|
| Default (interactive) | Full Q&A | Full | Approved by user | Approved by user | Configurable | Skipped (approved inline) |
| `--light` | Skipped | Reduced (inferred) | Internal default | Internal | Optional | Full section-by-section at end |
| `--autonomous` (or `/xplana`) | Skipped | **Full** | Internal (best-fit) | Internal (best-fit) | **Full (always)** | Plan-as-artifact presentation at end |

**`--light`**: fast path. Reduced depth, minimal interaction. Skips Phases 0.5, 1.5, 2.5, 2.6, and 2.7. Traditional section-by-section walkthrough at the end.

**`--autonomous`**: deep path. Maximum depth, zero interruption until the final gate. Runs the full research pipeline (all 7 agents), full review (security + architecture + business logic), and the self-review loop. Tech stack, scope, naming, and multi-agent setup are inferred and documented in `decisions.md`. At Phase 6 the completed plan is presented as a single structured artifact with every inferred default called out, then the (non-bypassable) Phase 6.5 final execution gate fires. Pick this when you know exactly what you want to plan and prefer reviewing a finished artifact over answering questions during creation. Correct any wrong inferences with `/xplan --deepen ~/code/plans/{concept-name}` rather than re-running from scratch.

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

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/xplan.md` | command | Main planning and execution command (/xplan) |
| `commands/xplana.md` | command | Autonomous alias - /xplana invokes /xplan --autonomous |
| `commands/xplan-status.md` | command | Plan progress dashboard (/xplan-status) |
| `commands/xplan-resume.md` | command | Resume interrupted execution (/xplan-resume) |
| `lib/xplan-status-gather.sh` | lib | Helper script that gathers plan progress data for /xplan-status |
| `lib/xplan-web-review.py` | lib | Local web server that renders plan.md in browser with section-level comment support for Phase 6 review |

## Dependencies

- **multi-agent**: Required for parallel agent execution during research, review, and implementation phases
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
