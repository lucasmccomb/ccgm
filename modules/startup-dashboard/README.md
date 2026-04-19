# startup-dashboard

`/startup` produces a short, nicely-formatted markdown summary of the current
repo state — what's happened in the last 48 hours, what's open, and what to
work on next. Deterministic data gather + model-powered summarization.

## What This Module Does

- **`/startup` command**: runs the gather pipeline, feeds the output to a
  headless Sonnet model, and emits a high-signal summary with sections for
  Where we are / Recent activity / Open PRs / Top open issues / Live sessions /
  Next up.
- **Gather pipeline**: collects git state, open PRs, 48h merges, priority
  issues, `tracking.csv` claims, live Claude Code sessions, sibling branches,
  orphan processes, release info, and recent session activity in parallel.
- **Recent Activity**: unified 7-day view of session transcripts across every
  clone of the current repo, powered by the `session-history` module's `/recall`.

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/startup.md` | command | `/startup` invokes the summary script |
| `lib/startup-gather.sh` | lib | Parallel data gather, emits `=== SECTION ===` blocks |
| `lib/startup-summary.sh` | lib | Runs the gather → model → markdown summary pipeline with a fallback chain |
| `lib/startup-summary-prompt.md` | lib | Fixed summary instructions the model receives |
| `lib/startup-dashboard.sh` | lib | Deterministic plain-text dashboard (fallback / `--raw` mode) |

## Dependencies

- `session-history` — supplies `~/.claude/scripts/recall.py`, which powers the Recent Activity block.

## Running

```
/startup           # Intelligent markdown summary
/startup --raw     # Deterministic plain-text dashboard (bypasses model)
```

Or directly:

```
bash ~/.claude/lib/startup-summary.sh
bash ~/.claude/lib/startup-dashboard.sh   # raw dashboard only
bash ~/.claude/lib/startup-gather.sh      # raw structured sections for debugging
```

## How summarization works — fallback chain

`startup-summary.sh` tries three paths in order, stopping at the first that
returns non-empty output:

1. **macOS Keychain → direct Anthropic API** (`~$0.015/run`). Requires a
   one-time Keychain entry (see below). Never exports `ANTHROPIC_API_KEY`, so
   new `claude` sessions keep their subscription / Max auth.
2. **`claude -p` subprocess** (`~$0.16/run`). No setup. Loads the full Claude
   Code CLI harness as a system prompt, hence the higher cost.
3. **Deterministic dashboard**. Zero model tokens. Used when no `claude`
   binary is installed or every model path fails.

### Enabling the cheap path (macOS only)

```bash
security add-generic-password -s ccgm-anthropic-api-key -a "$USER" -w sk-ant-...
```

macOS will prompt "Always Allow" the first time `security` reads the entry;
after that it is silent. To remove it:

```bash
security delete-generic-password -s ccgm-anthropic-api-key
```

### Tuning

All override-able via env vars at the top of `startup-summary.sh`:

| Variable | Default |
|----------|---------|
| `CCGM_SUMMARY_MODEL` (for `claude -p`) | `sonnet` |
| `CCGM_SUMMARY_MODEL_API` (for direct API) | `claude-sonnet-4-6` |
| `CCGM_KEYCHAIN_SERVICE` | `ccgm-anthropic-api-key` |

## Customizing

- Tune the summary style by editing `lib/startup-summary-prompt.md`.
- Add new sections to the gather by editing `lib/startup-gather.sh`; the
  prompt will see them automatically.
