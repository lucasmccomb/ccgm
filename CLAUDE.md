# CLAUDE.md - CCGM Repository

Instructions for Claude Code when working on the CCGM (Claude Code God Mode) repository itself.

## What This Repo Is

CCGM is a modular Claude Code configuration system. It contains 79 modules that users can selectively install to configure Claude Code's behavior, hooks, commands, and permissions.

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
│   └── statusline.sh   # Status line script
├── modules/            # 79 self-contained modules
│   └── {name}/
│       ├── module.json # Manifest
│       ├── README.md   # Module docs
│       └── ...         # Content files
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

All four are **default OFF**. Autoheal stays observation-only until you opt in.

| Key | Default | What it gates |
|-----|---------|---------------|
| `realtime_alerts_enabled` | `false` | Mid-session `<autoheal-security-alert>` blocks on high-confidence patterns (`ghp_*` in commits, `rm -rf /`, force-push to main) |
| `auto_apply_enabled` | `false` | Confidence-gated auto-apply (confidence ≥9, breadth ≤1, `settings_allow_add` only). Creates feature branch; never pushes |
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

The `modules/dreaming/` directory holds CCGM's nightly, cost-capped transcript-mining pipeline. It mines session transcripts into evidence-tagged `self-improving` learnings-store proposals. Every proposal is human-reviewed via `/dream-apply` by default; an opt-in **optimistic auto-integration** engine (`optimistic_integration.enabled`, default `false`) can integrate them instead, behind a per-op-kind posture (immediate for `verify`, a dwell window for `add`/`supersede`/`contradict`/`deprecate`), per-slug blast-radius caps, a batch-anomaly check, and a windowed circuit breaker.

### Dreaming bring-up

```bash
bash start.sh --add dreaming                          # install lib/bin/commands/rules
bash modules/dreaming/bin/dream-install.sh            # register the macOS LaunchAgent
bash modules/self-improving/bin/memory-setup.sh       # activation prompts: read path, dreaming, optimistic mode
```

`memory-setup.sh` is the activation forcing-function for both the write path and optimistic mode — the operator is never expected to hand-edit `~/.claude/dreaming/config.json` to turn either on.

### Config (`~/.claude/dreaming/config.json`)

| Key | Default | What it gates |
|-----|---------|---------------|
| `optimistic_integration.enabled` | `false` | Opt-in auto-integration engine. A legacy `auto_apply_counters: true` config is migrated automatically (in-memory, on read) to `optimistic_integration.enabled: true` with the same conservative defaults |
| `optimistic_integration.dwell_hours` | `24` | Hours a written `add`/`supersede`/`contradict`/`deprecate` row is excluded from `search()`/injection before going live |
| `optimistic_integration.max_add_supersede_per_run` | `10` | Per-slug, per-night cap on `add` + `supersede` |
| `optimistic_integration.max_eviction_absolute` / `max_eviction_fraction_per_run` | `3` / `0.20` | Per-slug, per-night cap on `contradict` + `deprecate` — the smaller of the two dominates |

### Dreaming slash commands

| Command | Purpose |
|---------|---------|
| `/dream` | Status overview + subcommand surface. Read-only |
| `/dream-digest [date]` | Render today's (or a date's) digest |
| `/dream-apply [id\|list]` | Always-available, human-gated apply — accept/reject a pending proposal |
| `/dream-review [id\|list]` | Post-hoc review of auto-integrated and still-dwelling rows; veto one before it goes live |
| `/dream-scorecard [week]` | Read-only weekly observability scorecard |

Rollback for a bad auto-integrated batch is `ccgm-learnings-sync revert <sha>` (in `self-improving`) — not a raw `git revert`, which is unsound against this store's `merge=union` shard files.

### Eval harness (`bin/dream-eval.sh`)

`dream-eval.sh --gate` is the regression gate the optimistic engine must pass nightly. Two rules keep a red gate meaningful, after seven weeks (2026-07-15 to 2026-09-02) in which every nightly run scored 100% format errors because the LaunchAgent's PATH did not include `~/.local/bin`, where Claude Code's native installer puts the CLI:

- The `claude` binary is resolved to an absolute path before any task runs; an unresolvable binary fails the run immediately, naming what it searched, instead of spending anything.
- A run where **every** agent run failed to execute aborts with the first failure's raw output on stderr and exit 1, writing no results file and recording `evals/<date>.harness-broken`. While that marker is newer than the newest results file, `--gate` reports `harness broken: ...` — without it an abort would leave the gate reading the previous run's file and reporting `open`. Any run that produces results clears every marker.
- A run that never executed moves no score, in either direction: it skips the judge and is excluded from every mean, and any arm holding one buckets the row `error`. So a *partial* harness failure can only close the gate, never open it — flooring such a run to zero instead was enough, at two failures in a five-run arm, to manufacture a `high_value` row.

The judge is one Messages API call per run: no sampling parameters (current judge models 400 on them), `thinking: {"type": "disabled"}`, and `output_config.format` pinning the `{pass, score}` schema. When reading a red gate, check the run wrote rows at all before treating it as a memory result.

### Dreaming posture

Human-gated apply (`/dream-apply`) is always on and requires no opt-in. Optimistic auto-integration is opt-in and off by default; every gate (eval regression, blast-radius caps, anomaly check, circuit breaker) is designed to hold even if the daily report is never read — only *undoing* an already-integrated row needs a read. See `modules/dreaming/rules/dreaming.md` for the full contract.

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
