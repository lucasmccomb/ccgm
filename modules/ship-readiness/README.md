# Ship Readiness

`/ship-ready` - a single-screen dashboard that answers "what is gating this
branch from merging?" before you open a PR or ask for review.

## Why This Exists

CCGM has `/cpm` (commit/PR/merge), `/pr` (push + create PR), and the
`pr-review-toolkit` reviewers, but nothing that projects all of the pre-merge
signals into one view. When you run four parallel agents, the question you
actually want answered is not "do tests pass?" but:

- Which branch has been reviewed by what?
- Are those reviews still fresh after the last few commits?
- Are any P0 findings still unresolved?
- Is there a known risk in `docs/solutions/` that this diff touches?

`/ship-ready` answers all of these in one place. It is read-only: it never runs
tests, never modifies files, never writes an artifact. It projects existing
state.

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `commands/ship-ready.md` | `commands/ship-ready.md` | `/ship-ready` slash command |

## The Dashboard

Eight sections, always in order:

1. **Current branch context** - branch, HEAD sha, ahead/behind base, file count
2. **Failing tests** - last CI or local test result; does NOT run tests
3. **Open PRs** - count, current-branch PR highlighted
4. **Stale branches** - local refs not touched in >14 days
5. **Outdated dependencies** - first recognized lockfile wins
6. **Recent merge velocity** - 24h / 7d / 30d bucket counts via `gh pr list`
7. **Review freshness** - reads `.context/ce-review/*.json` envelopes; commit
   staleness = `git rev-list --count {stored_head}..HEAD`
8. **Unresolved risks** - dispatches `learnings-researcher` over the branch
   diff, filters on `problem_type: bug`

Closes with a single `GATE:` line (`GREEN` / `YELLOW` / `RED`).

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/commands

cp modules/ship-readiness/commands/ship-ready.md \
   ~/.claude/commands/ship-ready.md
```

## Dependencies

None are hard dependencies - the command degrades gracefully if optional
modules are missing:

- **`ce-review`** (recommended) - provides the `.context/ce-review/*.json`
  envelopes that feed section 7 (review freshness). Without it, section 7
  prints "no /ce-review runs yet."
- **`compound-knowledge`** (recommended) - provides the `learnings-researcher`
  agent that feeds section 8 (unresolved risks). Without it, section 8 prints
  "compound-knowledge not installed."
- **`gh` CLI** (required for sections 3, 6, and CI status) - standard on any
  CCGM machine. Sections that require `gh` print `n/a (no GitHub access)`
  when it is absent or unauthenticated.

## Usage

```
/ship-ready                   # Dashboard for the current branch
/ship-ready base:origin/dev   # Override the base ref (default: origin/main)
/ship-ready mode:strict       # Exit non-zero on RED gate (for CI or /cpm wiring)
```

## Gating Rules

Only three signals are hard blockers (`RED`):

- CI reported test failure on HEAD
- P0 finding in the latest `/ce-review` envelope
- Current branch behind base by any commits

Stale reviews, outdated deps, and neighbor-branch staleness are `YELLOW` -
informational, not gating. Missing review against the current base is `RED`
because "no review at all" is a gate in a way that "old review" is not.

Default mode always exits zero. `mode:strict` is the opt-in for wiring into
`/cpm` or a CI pre-merge step.

## Non-Goals

This module does **not**:

- Run tests, linters, or type-checkers (`/ce-review` covers that ground)
- Dispatch `/ce-review` automatically. Review runs remain user-driven.
- Write any artifact. No session log entry, no checkpoint file.
- Enforce gating. `mode:strict` reports the verdict; the caller decides what
  to do with it.
- Mirror gstack's JSONL review log. CCGM uses the `/ce-review` envelopes that
  already exist instead of introducing a parallel log.

## Source

Ported from garrytan/gstack's `ship/SKILL.md:667-728` (dashboard layout,
gating logic) and `bin/gstack-review-read:1-12` (commit-hash staleness
detection).

CCGM adaptations:

- Source of truth is `.context/ce-review/*.json` envelopes, not
  `~/.gstack/projects/{slug}/{branch}-reviews.jsonl`. One log per review
  pipeline.
- Staleness detection uses `git rev-list --count {stored_head}..HEAD` to
  count commits since the review - identical to gstack's approach.
- Only three RED blockers (CI fail, P0 finding, branch-behind-base). gstack
  has a richer persona model (Eng / CEO / Design / Adversarial / Outside
  Voice); CCGM's `/ce-review` collapses those into one orchestrated pipeline,
  so the dashboard has one "review" signal to project.
- Unresolved-risk section reads `docs/solutions/` via the existing
  `learnings-researcher` agent (compound-knowledge module) instead of a
  gstack-specific retrieval script.
