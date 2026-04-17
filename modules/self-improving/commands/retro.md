---
description: Generate a retrospective from git history over a time window (default last 7 days)
---

# /retro - Weekly Retrospective from Git History

Synthesize what was shipped in a time window by walking the git log, surfacing
hotspots, per-author activity, and patterns worth capturing as learnings. Pairs
with `/reflect` (in-session pattern capture) and `/consolidate` (memory cleanup)
as the "look back across days, not just the session" tool.

Different from `/reflect`: `/reflect` introspects one session. `/retro` surveys
all commits across the window - including work by other agents in sibling
clones, by co-workers, and by past sessions you no longer remember.

## Usage

```
/retro                     # Last 7 days, this repo
/retro [N]d                # Last N days (e.g. /retro 14d)
/retro [YYYY-MM-DD]        # From that date through today
/retro global              # Aggregate across ALL repos under the code directory
/retro global [window]     # Global + windowed
```

No argument defaults to `7d`.

## When to Use

- End-of-week summary of what shipped across your clones and branches.
- Sunday planning - review what moved, decide what to focus on next.
- After a multi-day feature lands - capture what patterns emerged while the
  work is still fresh.
- When an agent resumes on a long-running project and needs a quick ground
  truth of "what has happened here lately."

## Default (Per-Repo) Workflow

### 1. Resolve the Window

Midnight-aligned windows are important: "last 7 days" must anchor to local
midnight so the window is stable across the day, not sliding with the wall
clock. Compute the absolute start date first, then use it for all git queries.

```bash
# Parse the argument.
ARG="${ARG:-7d}"

if [[ "$ARG" =~ ^([0-9]+)d$ ]]; then
  N="${BASH_REMATCH[1]}"
  # Local midnight, N days ago. `date -v` for BSD/macOS; `date -d` for GNU.
  if date -v-1d >/dev/null 2>&1; then
    SINCE=$(date -v-"${N}"d +%Y-%m-%d)
  else
    SINCE=$(date -d "${N} days ago" +%Y-%m-%d)
  fi
elif [[ "$ARG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  SINCE="$ARG"
else
  echo "Usage: /retro [Nd|YYYY-MM-DD|global [window]]"
  exit 1
fi

# Git expects a timestamp. Anchor to local midnight.
SINCE_TS="${SINCE} 00:00:00"
UNTIL_TS=$(date +%Y-%m-%d)" 23:59:59"
```

Do NOT use `--since="7 days ago"` directly - that slides with invocation time
and produces different results at 9am vs 11pm on the same day.

### 2. Identify the Repo

```bash
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
[ -z "$REPO_NAME" ] && REPO_NAME=$(basename "$PWD")
```

Report the window and repo up front so the user can sanity-check the scope.

### 3. Gather Data (git log)

Run these queries inside the git root. All take `--since="$SINCE_TS" --until="$UNTIL_TS"`.

**Total commits and shortlog:**

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" --oneline | wc -l
git shortlog -sn --since="$SINCE_TS" --until="$UNTIL_TS"
```

**Per-author LOC (insertions/deletions):**

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" \
  --pretty=tformat:"%an" --numstat \
| awk '
    /^[^0-9]/ { author=$0; next }
    NF==3 && $1 ~ /^[0-9]+$/ { ins[author]+=$1; del[author]+=$2; files[author]++ }
    END { for (a in ins) printf "%s\t+%d / -%d\t(%d files)\n", a, ins[a], del[a], files[a] }
  ' | sort -t$'\t' -k2 -r
```

**Hotspots - most-changed files:**

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" --name-only --pretty=format: \
  | grep -v '^$' | sort | uniq -c | sort -rn | head -15
```

**Test-to-prod ratio** (rough heuristic - count files touched under test paths
vs other source paths):

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" --name-only --pretty=format: \
  | grep -v '^$' | awk '
    /test|spec|__tests__/ { tests++ ; next }
    /\.(md|json|yml|yaml|toml|lock)$/ { config++ ; next }
    { prod++ }
    END { printf "prod:%d  tests:%d  config/docs:%d  ratio(test/prod):%.2f\n",
          prod, tests, config, (prod>0 ? tests/prod : 0) }'
```

**PRs and issues referenced** (extract from commit messages - look for
`#NNN`, `Closes #NNN`, `Fixes #NNN`):

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" --pretty=%s%n%b \
  | grep -oE '#[0-9]+' | sort -u
```

**Session detection** - group commits into sessions by timestamp gaps. A gap
of > 4 hours between commits is a new session. Useful for "how many discrete
work sessions did I have this week."

```bash
git log --since="$SINCE_TS" --until="$UNTIL_TS" --pretty=%ct \
  | sort -n | awk '
    NR==1 { last=$1; sessions=1; next }
    ($1 - last) > 14400 { sessions++ }
    { last=$1 }
    END { print sessions }'
```

**Branches with recent activity:**

```bash
git for-each-ref --sort=-committerdate refs/heads/ refs/remotes/ \
  --format='%(committerdate:short) %(refname:short)' \
| awk -v since="$SINCE" '$1 >= since'
```

### 4. Merge Non-Git Context (optional)

If `~/.claude/retro-context.md` exists, read it. The user may jot meeting
notes, decisions, or context the git log cannot capture (e.g. "customer call
pushed the redesign to next week"). Include its contents in the retro under a
**Context from notes** section, verbatim and briefly.

Do NOT invent context. If the file is absent, skip the section.

### 5. Synthesize

The goal is a short retro note, not a data dump. Use the numbers to ground
observations; do not paste every query result verbatim.

Focus on:

- **Shipped** - what PRs merged, what features landed, what issues closed.
  Cross-reference PR numbers with `gh pr list --state merged --search "merged:>=${SINCE}"`
  if `gh` is available.
- **Hotspots** - which files churned the most, and why. A file at the top of
  the hotspot list that is not a generated artifact often signals unresolved
  design tension.
- **Patterns** - any topic that appears in 3+ commits ("kept adding edge
  cases to session validation," "three separate attempts at the cursor
  fix"). Call these out - they may be worth capturing to memory.
- **What took disproportionate time** - if one feature has 10 commits over
  three sessions and another has one commit, note the asymmetry. Ask why.
- **Test-to-prod ratio** - if it drifted low, flag it. If a whole area
  shipped with zero tests, name it.

### 6. Render the Retro

```markdown
# Retro: {REPO_NAME}  ({SINCE} - today)

**Sessions**: {N}   **Commits**: {N}   **PRs referenced**: #{a}, #{b}, ...

## Shipped

- {merged PRs / closed issues, 1 line each}

## Hotspots

- {path}  ({N} changes)  - {one-line observation}
- ...

## Per-author activity

| Author | Commits | LOC (+/-) | Files |
|--------|---------|-----------|-------|
| ...

## Patterns worth noting

- {any 3+ time topic, or test-ratio flag, or repeated-attempt pattern}

## Context from notes

{If ~/.claude/retro-context.md exists, 3-5 line summary of relevant bits.}

## Suggested follow-ups

- {1-3 concrete actions the user could take next - an issue to open, a
  refactor to plan, a pattern to capture via /reflect}
```

Keep it under one screen. A retro the user will not read is worse than no
retro.

### 7. Offer to Capture Patterns

After rendering, if any of the patterns look like reusable learnings
(recurring bug class, repeated gotcha, confirmed workflow preference), ask:

```
I noticed these potentially-reusable patterns:
  1. {pattern}
  2. {pattern}

Want me to capture any of these to memory via /reflect? (y/N/which)
```

Do NOT auto-write memory entries from a retro. Retros surface candidates;
`/reflect` confirms and writes them.

## Global Mode

`/retro global [window]` aggregates across every git repo under the user's
code directory. Use it for a weekly "what did I and my agents ship
everywhere" summary.

### 1. Discover Repos

```bash
CODE_DIR="${CODE_DIR:-$HOME/code}"
# Depth-limited find so we pick up both flat clones (e.g. `myrepo-repos/myrepo-0/.git`)
# and workspace clones (e.g. `myrepo-workspaces/myrepo-w0/myrepo-w0-c0/.git`).
find "$CODE_DIR" -maxdepth 4 -name ".git" -type d 2>/dev/null \
  | sed 's#/.git$##' | sort -u
```

Deduplicate by upstream remote URL - multiple clones of the same repo should
count once. Use `git remote get-url origin` from each directory and group.

### 2. Use Multi-Agent Tracking (if present)

If `multi-agent` is installed and a log repo exists at
`~/code/{log-repo}/{repo}/tracking.csv`, use it to enrich the retro with
issue-level state (claimed, in-review, merged, closed) beyond raw commits.

```bash
LOG_REPO_DIR="$HOME/code/${LOG_REPO_NAME:-agent-logs}"
for csv in "$LOG_REPO_DIR"/*/tracking.csv; do
  [ -f "$csv" ] || continue
  echo "=== $(dirname "$csv" | xargs basename) ==="
  # Filter rows whose state-change timestamp falls in the window.
  awk -F, -v since="$SINCE" 'NR>1 && $NF >= since' "$csv"
done
```

If no tracking CSV exists, skip this step silently.

### 3. Run the Per-Repo Workflow Per Repo

For each discovered repo, run steps 3-5 of the per-repo workflow but produce
a compact 3-5 line summary per repo, not a full retro. Then aggregate:

```markdown
# Global Retro  ({SINCE} - today)

**Repos active**: {N}   **Total commits**: {N}   **Total sessions**: {N}

## By repo

- **{repo-a}**: {commits}, {hotspot}, {headline}
- **{repo-b}**: {commits}, {hotspot}, {headline}
- ...

## Cross-repo patterns

- {any theme that shows up in 2+ repos, e.g. "tightened test coverage across
  darkly-suite and habitpro-ai"}

## Agent activity (from tracking.csv)

- {repo}: {N} issues claimed, {N} merged, {N} closed
- ...
```

## Conventions

- Midnight-align every window. Never use raw `--since="N days ago"`.
- Never auto-write memory entries from a retro - ask first, run `/reflect`
  for the confirmed ones.
- Do not include secrets, tokens, or API keys from commit messages or notes
  in the rendered retro. If a match appears in a diff, reference it as
  `[redacted credential]` and flag as a follow-up.
- Keep the rendered retro under one screen. Link out to the full git log for
  anyone who wants the raw data.
- Honor the `~/.claude/retro-context.md` hook if it exists. The user is
  opting in to layering non-git context; respect their format.

## Cross-Module Integration

- **self-improving** - `/retro` surfaces candidate patterns; `/reflect`
  writes them to memory; `/consolidate` maintains them.
- **multi-agent** - global mode reads `tracking.csv` to report agent-level
  issue state alongside commit activity.
- **session-logging** - the log repo is the durable record of what happened
  session-by-session; retro is the windowed git-ground summary that
  complements it.
