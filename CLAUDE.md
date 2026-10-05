# CLAUDE.md - CCGM Repository

Instructions for Claude Code when working on the CCGM (Claude Code God Mode) repository itself.

## What This Repo Is

CCGM is a modular Claude Code configuration system. It contains 81 modules that users can selectively install to configure Claude Code's behavior, hooks, commands, and permissions.

## Repository Structure

```
ccgm/
├── start.sh            # Main entry point (bash)
├── update.sh           # Check for upstream changes
├── uninstall.sh        # Clean removal
├── lib/                # Installer utilities
│   ├── ui.sh           # TUI (pure bash with ANSI escapes)
│   ├── template.sh     # __PLACEHOLDER__ expansion
│   ├── merge.sh        # settings.json merge via jq
│   ├── modules.sh      # Module discovery + deps
│   ├── backup.sh       # Backup/restore
│   ├── mcp-migrate.sh  # Legacy mcp.json re-registration
│   ├── repair.sh       # Stale symlink repair
│   ├── compose-sections.py  # Expands prompts/sections into agent and command files (--check gates CI)
│   ├── rule_tiering.py # Rule-tiering support library (paths: frontmatter)
│   └── statusline.sh   # Status line script
├── modules/            # 81 self-contained modules
│   └── {name}/
│       ├── module.json # Manifest
│       ├── README.md   # Module docs
│       └── ...         # Content files
├── prompts/            # Shared prompt text
│   └── sections/       # One file per repeated passage, inlined by compose-sections.py
├── presets/            # Named module collections
│   ├── minimal.json
│   ├── standard.json
│   ├── full.json
│   ├── team.json
│   └── cloud-agent.json
└── tests/              # Test scripts
```

## Key Rules

### No Personal Data

This is a public repo. NEVER commit:
- GitHub usernames (e.g., specific user handles)
- Personal directory paths (e.g., /Users/specific-user)
- Service project IDs (Supabase refs, API endpoints)
- Personal repo names

Run the verification check before committing:
```bash
bash tests/test-no-personal-data.sh
```

### Module Development

Each module is self-contained in `modules/{name}/`:
- `module.json` defines metadata, files, dependencies, and config prompts
- Content files go in subdirectories matching their target location (rules/, commands/, hooks/, skills/, agents/)
- Rule files (rules/*.md) use generic language, NOT template variables
- Config files (hooks, settings) may use `__PLACEHOLDER__` template variables

### Template Variables

Used only in config files (not rule files):
- `__HOME__` - User's home directory
- `__USERNAME__` - GitHub username
- `__CODE_DIR__` - Code workspace directory
- `__TIMEZONE__` - User's timezone
- `__DEFAULT_MODE__` - Permission default mode (ask/dontAsk)

### Testing

Before submitting changes:
```bash
# Validate all modules
bash tests/test-modules.sh

# Check for personal data leaks
bash tests/test-no-personal-data.sh

# Test installer (in temp directory)
bash tests/test-installer.sh
```

### Adding a New Module

1. Create `modules/{name}/` directory
2. Create `module.json` following the schema in existing modules
3. Add content files in appropriate subdirectories
4. Create `README.md` with manual installation instructions
5. Add to relevant presets in `presets/`
6. Run tests

### Shared Prompt Sections

Passages repeated across `modules/*/agents/` and `modules/*/commands/` files live once in `prompts/sections/<name>.md` (repo root, not installed). A file uses one by wrapping the expansion in `<!-- ccgm:section <name> -->` and `<!-- /ccgm:section <name> -->`; the section text is inlined between them, so installed files stay plain markdown. Edit the section, then run `python3 lib/compose-sections.py` before committing to rewrite every block. CI runs `python3 lib/compose-sections.py --check` and fails on drift. Rule files are out of scope.

### Editing Module Files via Symlinks

CCGM module files are installed at `~/.claude/{commands,lib,hooks,rules}/` as **symlinks** pointing at `~/code/ccgm/modules/.../`. The Edit tool tracks reads by absolute path and does NOT follow symlinks — reading an installed copy does not satisfy Edit's read-gate for the workspace source path.

When editing a module file from a workspace clone:

- Source (edit here): `modules/{name}/.../file` under the current workspace clone
- Installed symlink: `~/.claude/lib/file.py` or similar — fine to Read for inspection, but does NOT count toward the Edit gate for the workspace source path
- Canonical clone: `~/code/ccgm/modules/...` — same: do not edit here, do not rely on its read state

Habit: always Read the workspace `modules/` path before any Edit, even if you read the installed copy first.

## Autoheal Module

The `modules/autoheal/` directory holds CCGM's self-healing observability loop. It captures permission events, tool failures, and user-correction signals to a local JSONL log, runs a daily analyzer via direct Anthropic API call, and surfaces a digest of proposed configuration improvements.

### Autoheal bring-up

```bash
bash start.sh --add autoheal                         # install hooks/commands/rules/scripts
bash modules/autoheal/bin/autoheal-install.sh        # register the macOS LaunchAgent (Epic 6)
```

See `plan.md §9.1` for the full per-wave bring-up runbook.

### Config flags (`~/.claude/autoheal/config.json`)

All four are **default OFF**. The first two take `off|shadow|active` (a persisted boolean reads as active/off; shadow logs the decision and acts on nothing). Autoheal stays observation-only until you opt in.

| Key | Default | What it gates |
|-----|---------|---------------|
| `realtime_alerts_enabled` | `off` (`off\|shadow\|active`) | Mid-session `<autoheal-security-alert>` blocks on high-confidence patterns (`ghp_*` in commits, `rm -rf /`, force-push to main) |
| `auto_apply_enabled` | `off` (`off\|shadow\|active`) | Confidence-gated auto-apply (confidence ≥9, breadth ≤1, `settings_allow_add` only). Creates feature branch; never pushes |
| `email_enabled` | `false` | Resend-backed email digest (requires `digest_email` + `RESEND_API_KEY`) |
| `webhook_url` | `null` | When set, daily run POSTs proposals/events/digests to `${webhook_url}/v1/ingest`. **Future-integration point for `dev.lem.work`** — receiver lives outside this repo. `webhook_token` (32-char Bearer) is generated at install time |

Per-repo overrides live in `.autoheal/config.json` at the repo root. Both files are gitignored.

### Autoheal slash commands

| Command | Purpose |
|---------|---------|
| `/autoheal` | Help + status |
| `/autoheal-digest [date]` | Render today's (or a date's) digest |
| `/autoheal-toggle [pause\|resume\|status\|realtime\|autoapply\|webhook]` | Flip config flags |
| `/autoheal-snooze <id> [days]` | Snooze a proposal for N days (default 7) |
| `/autoheal-apply [id\|list]` | Formal apply path; feature branch + validation tests + audit |
| `/permission-fix [event-id\|latest]` | In-session root-cause sub-agent for a permission failure |
| `/permission-audit` | Static audit of installed hooks + settings against the classification table |

### Autoheal posture

Autoheal is opt-in by design. The default install only captures events and surfaces a local digest. Nothing alerts mid-session, nothing auto-applies, no network calls leave the machine. Each opt-in is a deliberate `/autoheal-toggle` away.

## Dreaming Module

The `modules/dreaming/` directory holds CCGM's nightly, cost-capped transcript-mining pipeline. It mines session transcripts into evidence-tagged `self-improving` learnings-store proposals. It mines what a session cannot see for itself (redirections, resolved struggles, conclusions, rediscovered facts, abandoned work), drops what the session already loads (rules, CLAUDE.md, auto-memory, hook text), and leaves tool and hook friction to autoheal. No human queue: with the opt-in **optimistic auto-integration** engine active (`optimistic_integration.enabled`, default `off`), every proposal ends integrated or discarded with a reason, behind a per-op-kind posture (immediate for `verify`, a dwell window for `add`/`supersede`/`contradict`/`deprecate`), per-slug blast-radius caps, a batch-anomaly check, an eval gate and a circuit breaker. With the engine off, proposals are held untouched and `/dream-apply` is the manual path. Each night writes `state/health.json`, a SessionStart hook surfaces a red status and a one-line daily notice, a recurrence metric (`lib/recurrence.py`, no API cost) auto-verifies or deprecates learnings, and an opt-in weekly regression smoke (about $1.50) guards against regressions.

### Dreaming bring-up

```bash
bash start.sh --add dreaming                          # install lib/bin/commands/hooks/skill
bash modules/dreaming/bin/dream-install.sh            # register the macOS LaunchAgent
bash modules/self-improving/bin/memory-setup.sh       # activation prompts: read path, dreaming, optimistic mode
```

`memory-setup.sh` is the activation forcing-function for both the write path and optimistic mode — the operator is never expected to hand-edit `~/.claude/dreaming/config.json` to turn either on.

### Config (`~/.claude/dreaming/config.json`)

| Key | Default | What it gates |
|-----|---------|---------------|
| `optimistic_integration.enabled` | `off` (`off\|shadow\|active`) | Opt-in auto-integration engine; shadow logs would-integrate and writes nothing, and `/dream-scorecard` tallies it. A legacy `auto_apply_counters: true` config is migrated automatically (in-memory, on read) to `optimistic_integration.enabled: true` with the same conservative defaults |
| `optimistic_integration.dwell_hours` | `24` | Hours a written `add`/`supersede`/`contradict`/`deprecate` row is excluded from `search()`/injection before going live |
| `optimistic_integration.max_add_supersede_per_run` | `10` | Per-slug, per-night cap on `add` + `supersede` |
| `optimistic_integration.max_eviction_absolute` / `max_eviction_fraction_per_run` | `3` / `0.20` | Per-slug, per-night cap on `contradict` + `deprecate` — the smaller of the two dominates |
| `optimistic_integration.pending_max_age_hours` | `48` | A proposal still pending this long is discarded as `expired` (active mode only) |
| `optimistic_integration.eval_freshness_days` | `7` | Eval results older than this pause the gate |
| `optimistic_integration.max_unevaluated_writes` | `15` | More dreaming auto writes than this since the last eval pause the gate |
| `optimistic_integration.eval_refresh_enabled` | `false` | Nightly chain runs the weekly 24-session regression smoke (about $1.50) |
| `optimistic_integration.eval_refresh_min_age_days` | `7` | Newest eval results must be this old before a refresh |
| `optimistic_integration.eval_refresh_cost_cap_usd` | `2.0` | Hard stop for one refresh run |
| `optimistic_integration.eval_oauth_token_file` | unset | File with a `claude setup-token` token, so the smoke's arms bill the subscription |
| `module_budget_usd_30d` | `25.0` | Rolling 30-day ceiling over all `cost.log` spend (analyzer, eval, judge, manual runs); the analyzer and eval refuse to start at or above it |
| `eval_run_cost_cap_usd` | `5.0` | Hard cap on one `memory_eval.py` run |
| `daily_cost_cap_usd` | `10.0` | Preflight cap on one night's analyzer spend |
| `prefilter_threshold` | `0.35` | Map candidates scoring at or above this against the loaded-context corpus are dropped as `already_encoded` (above 1 turns it off) |
| `friction_threshold` | `0.35` | Friction-only candidates restating their tool error at or above this are dropped as `routed_to_autoheal` (above 1 turns it off) |
| `promotion_min_sessions` / `promotion_min_slugs` | `3` / `2` | Sessions and project slugs a `_global` add's verified evidence must span to promote; otherwise it is rescoped to one slug |
| `reduce_pending_max` | `100` | Most pending proposals the reduce sees |

The module README's "Configuration reference" lists every key.

### Dreaming slash commands

| Command | Purpose |
|---------|---------|
| `/dream` | Status overview + subcommand surface. Read-only |
| `/dream-digest [date]` | Render today's (or a date's) digest |
| `/dream-apply [id\|list]` | Manual override — accept/reject a pending proposal. The only path while integration is `off` or `shadow`; nothing waits for it when `active` |
| `/dream-review [id\|list]` | Post-hoc review of auto-integrated and still-dwelling rows; veto one before it goes live |
| `/dream-scorecard [week]` | Read-only weekly observability scorecard; headline is the recurrence reduction |

Rollback for a bad auto-integrated batch is `ccgm-learnings-sync revert <sha>` (in `self-improving`) — not a raw `git revert`, which is unsound against this store's `merge=union` shard files.

### Eval harness (`bin/dream-eval.sh`)

`dream-eval.sh --gate` is the regression gate the optimistic engine must pass nightly. Two rules keep a red gate meaningful, after seven weeks (2026-07-15 to 2026-09-02) in which every nightly run scored 100% format errors because the LaunchAgent's PATH did not include `~/.local/bin`, where Claude Code's native installer puts the CLI:

- The `claude` binary is resolved to an absolute path before any task runs; an unresolvable binary fails the run immediately, naming what it searched, instead of spending anything.
- A run where **every** agent run failed to execute aborts with the first failure's raw output on stderr and exit 1, writing no results file and recording `evals/<date>.harness-broken`. While that marker is newer than the newest results file, `--gate` reports `harness broken: ...` — without it an abort would leave the gate reading the previous run's file and reporting `open`. Any run that produces results clears every marker.
- **A launch failure may only move a row toward a closed gate, never toward an open one.** A run that never executed skips the judge and is excluded from every mean (except cost — that is spend, not quality), and any arm holding one downgrades the row to `error` — except a `regression`, which is preserved, since the gate selects regressions by bucket name and relabelling one would hide it. `downgrade_bucket_for_launch_failures()` is the single place that decides this.

The judge is one Messages API call per run: no sampling parameters (current judge models 400 on them), `thinking: {"type": "disabled"}`, and `output_config.format` pinning the `{pass, score}` schema. When reading a red gate, check the run wrote rows at all before treating it as a memory result.

### Dreaming posture

Nothing waits on a person. Optimistic auto-integration is opt-in and off by default; with it off, proposals are held (never discarded) and `/dream-apply` is the manual path. With it on, every gate (eval regression, blast-radius caps, anomaly check, circuit breaker) is designed to hold even if the daily report is never read — only *undoing* an already-integrated row needs a read. The weekly regression smoke is a second opt-in (`eval_refresh_enabled`); until it runs, the gate pauses once results go stale, and a pause of 3 or more nights turns `health.json` red. See `modules/dreaming/skills/dreaming/SKILL.md` and the module README for the full contract.

## Commit Message Format

```
#{issue_number}: {description}
```

## Branch Workflow

Feature branches from main. PRs with squash merge.

## Post-Merge: Always Run /docupdate

**After every PR merge to this repo**, run `/docupdate` before moving on. This keeps module counts, phase lists, command references, and feature descriptions in sync with the actual codebase.

This also applies after running `/ccgm-sync` - if files changed, docupdate catches any documentation drift introduced by the sync.

This is non-negotiable for this repo because the docs describe the modules themselves. A new module without updated counts or a changed command without updated descriptions silently misleads users.
