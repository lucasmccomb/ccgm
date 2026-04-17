---
description: Ship readiness dashboard. One screen showing what gates a merge on the current branch - failing tests, open PRs, stale branches, outdated deps, merge velocity, review freshness, and unresolved risks.
---

# /ship-ready - Ship Readiness Dashboard

Render a single-screen dashboard summarizing whether the current branch is ready
to merge. Use before opening a PR, before asking for review, or at any point
when you want to know "what's blocking this?" without reading five different
tool outputs.

When you run multiple parallel agents, the question you actually want answered
before merging any one of them is: which branch has been reviewed by what, and
whether those reviews are still fresh after the last few commits. This is that
answer.

## Usage

```
/ship-ready                   # Dashboard for the current branch
/ship-ready base:origin/main  # Override the base ref for diffs and review lookup (default: origin/main)
/ship-ready mode:strict       # Exit non-zero if any gate is red; for CI or for blocking /cpm
```

`/ship-ready` is read-only. It never modifies files, never runs tests, never
installs packages. If a signal requires a running process (e.g. `npm test`), it
reports the last known result and a note on how to refresh it, not a live run.

## What the Dashboard Shows

The dashboard has seven sections, always in this order. Skip a section if the
underlying data is unavailable - note the reason inline rather than printing an
empty block.

### 1. Current branch context

```bash
BRANCH=$(git branch --show-current 2>/dev/null || echo detached)
HEAD_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
BASE_REF="${BASE_REF:-origin/main}"
AHEAD=$(git rev-list --count "${BASE_REF}..HEAD" 2>/dev/null || echo ?)
BEHIND=$(git rev-list --count "HEAD..${BASE_REF}" 2>/dev/null || echo ?)
DIFF_FILES=$(git diff --name-only "${BASE_REF}...HEAD" 2>/dev/null | wc -l | tr -d ' ')
```

Print:

```
Branch: {branch}  @  {head_sha}
Base:   {base_ref}  (ahead: {ahead}, behind: {behind})
Files changed on branch: {diff_files}
```

### 2. Failing tests

Detect the project's test runner from common signals:

- `package.json` with `scripts.test` - report `npm test` / `pnpm test`
- `pytest.ini`, `pyproject.toml` (`[tool.pytest]`), or `tests/` - report `pytest`
- `Gemfile` with rspec - report `bundle exec rspec`
- `go.mod` - report `go test ./...`
- Other - report "no recognized test runner"

Do NOT run the tests. Instead, look for a recent result artifact:

- `.last-test-result` file at repo root (if the project writes one)
- Most recent file under `test-results/`, `coverage/`, or `reports/` (mtime-based)
- CI status on the HEAD commit via `gh run list --branch {branch} --limit 1 --json status,conclusion,updatedAt`

If no recent artifact or CI run is available, print:

```
Tests: UNKNOWN (no recent run found; suggest: {suggested-command})
```

If CI ran and failed, print:

```
Tests: RED    CI conclusion: failure  ({updatedAt})
              Rerun: gh run rerun {run-id}
```

If CI passed within the last 2 hours AND the commit matches HEAD, print:

```
Tests: GREEN  CI conclusion: success  ({updatedAt}, on {head_sha})
```

Otherwise (result exists but older than 2 hours OR commit drifted), print
`STALE` with the age and the SHA drift.

### 3. Open PRs

```bash
gh pr list --state open --json number,title,headRefName,updatedAt --limit 50 \
  2>/dev/null
```

Print a compact table:

```
Open PRs: {N}
  #{num}  {title}  ({headRefName}, updated {relative-age})
  ...
```

If the current branch has an open PR, highlight it:

```
-> #{num}  THIS BRANCH  {title}  (updated {relative-age})
```

If no PR exists for the current branch, add a hint:

```
No PR for this branch. Open one with: gh pr create
```

### 4. Stale branches

A branch is stale if its tip has not moved in more than 14 days. Compute from
local refs (the user's working copy is authoritative for their own branches):

```bash
NOW=$(date +%s)
git for-each-ref --format='%(refname:short) %(committerdate:unix)' refs/heads \
  | while read name ts; do
      age_d=$(( (NOW - ts) / 86400 ))
      if [ "$age_d" -gt 14 ]; then
        printf '%s\t%d\n' "$name" "$age_d"
      fi
    done
```

Print up to 10, newest first among stale:

```
Stale branches (>14d, local): {N}
  {branch}  ({N}d)
  ...
```

Suggest cleanup only if the user has the `deadhead` alias available (it's
mentioned in the repo's CLAUDE.md aliases). Otherwise just list.

### 5. Outdated dependencies

Check the first lockfile that exists, in this order:

- `pnpm-lock.yaml` -> `pnpm outdated --format json 2>/dev/null`
- `package-lock.json` or `npm-shrinkwrap.json` -> `npm outdated --json 2>/dev/null`
- `yarn.lock` -> `yarn outdated --json 2>/dev/null`
- `Gemfile.lock` -> `bundle outdated --parseable 2>/dev/null`
- `uv.lock` or `poetry.lock` -> skip (no fast JSON surface; note the lockfile)
- `Cargo.lock` -> `cargo outdated --format json 2>/dev/null` if installed

Parse the JSON. Print the count only - not the full list:

```
Outdated deps: {N}  (via {manager})
  Major: {Nm}   Minor: {Nn}   Patch: {Np}
  Details: {manager} outdated
```

If the command is slow (>5s), abort and print `SKIPPED (slow)`. Do not hang.

If no lockfile is recognized, print:

```
Outdated deps: n/a (no recognized lockfile)
```

### 6. Recent merge velocity

```bash
gh pr list --state merged --limit 20 \
  --json number,mergedAt,title 2>/dev/null
```

Bucket merges into the last 24h, last 7d, last 30d. Print:

```
Recent merges:  24h: {N}   7d: {N}   30d: {N}   (via gh pr list)
```

If `gh` is not authenticated or the repo has no remote, print:

```
Recent merges: n/a (no GitHub access)
```

### 7. Review freshness

This is the section that distinguishes `/ship-ready` from a generic status
dashboard. It answers: "have the reviews that were supposed to run on this
branch actually run, and are they still fresh?"

#### Source: ce-review envelopes

`/ce-review` writes one JSON envelope per run to:

```
.context/ce-review/{timestamp}-{base_ref_short}-{head_ref_short}.json
```

Each envelope has `base_ref`, `head_ref`, `mode`, `findings`, `adversarial`,
`scope_drift`, and a `summary` block. The envelope path encodes the commit
SHAs the review ran against. That is the key to staleness detection.

#### Algorithm

```bash
ENV_DIR=".context/ce-review"
if [ ! -d "$ENV_DIR" ]; then
  echo "Reviews: no .context/ce-review/ directory (no /ce-review runs yet)"
  # skip section and continue with the rest of the dashboard
fi
```

List envelopes, newest first. For each envelope:

1. Parse `base_ref` and `head_ref` from the JSON (not the filename - the
   filename has short SHAs that may collide).
2. Resolve the recorded `head_ref` to its SHA. If the ref no longer exists
   (branch was deleted), mark the review as `ORPHANED` and skip staleness.
3. Compute staleness: `git rev-list --count {head_ref_recorded}..HEAD` - this
   is how many new commits have landed on the current branch since the review
   ran. Zero means the review is still current.
4. Count findings by severity from `summary.p0` / `p1` / `p2` / `p3`.

Group envelopes by their `base_ref` so multiple reviews against the same base
are shown together (usually just one, but the pipeline can be re-run).

Print (one section per distinct base):

```
Reviews vs {base_ref}:
  /ce-review  ran {relative-age}  on {head_sha_short}
              commits since review: {N}  ({STATUS})
              findings: P0:{n}  P1:{n}  P2:{n}  P3:{n}
              auto-fixed: {n}   needs input: {n}   red-team: {n}
```

Where `STATUS` is:

- `CURRENT` if `N == 0`
- `STALE` if `1 <= N <= 5`
- `VERY STALE` if `N > 5`
- `ORPHANED` if the recorded `head_ref` does not resolve

If no envelope exists for the current `(base_ref, branch)` pair, print:

```
Reviews vs {base_ref}:
  /ce-review  NOT RUN on this branch
              Run: /ce-review
```

Any P0 finding in the most recent envelope is always surfaced. Print its
`title` verbatim in a `BLOCKING` subsection. Do not paraphrase.

### 8. Unresolved risks from docs/solutions/

If the `learnings-researcher` agent is available (installed by the
`compound-knowledge` module), dispatch it with the branch diff summary:

```
Dispatch the learnings-researcher agent with:
- task_summary: "Pre-merge readiness check. Branch {branch} touches
  {diff_files_count} files including {top 3 paths}. Looking for prior
  learnings that flag unresolved risks, recent regressions, or known
  gotchas in these areas."
- files_hint: [first 10 paths from `git diff --name-only {base_ref}...HEAD`]
- tags_hint: []
- problem_type_filter: bug
- max_results: 5
```

Render the returned blocks under:

```
Unresolved risks (from docs/solutions/):
  {title}     ({relevance/10})
              {why_relevant}
              See: {path}
  ...
```

If the agent is not installed OR returns `no_solutions_directory: true`, print:

```
Unresolved risks: n/a (compound-knowledge not installed or no docs/solutions/)
```

Do NOT fall back to a manual grep of `docs/solutions/`. If the agent is absent,
the caller does not have the retrieval discipline installed and the dashboard
should not fake it.

## Gating Summary

At the very end, print a single gate line summarizing the whole dashboard:

```
GATE: {STATUS}   ({reason})
```

Where `STATUS` is:

- `GREEN` - no known blockers. Ready to ship.
- `YELLOW` - non-blocking concerns. Review the dashboard and decide.
- `RED` - at least one hard blocker (failing CI, P0 finding in latest review,
  current branch behind base by any amount).

Only these are hard blockers. Stale reviews, outdated deps, and stale
neighbor branches are YELLOW - they are informational, not gating. Review
staleness becomes RED only when there is NO review at all against the current
base ref.

In `mode:strict`, exit non-zero when `STATUS` is `RED`. In default mode, always
exit zero - the dashboard is informational by design.

## Output Style

Keep it compact. The whole dashboard should fit in one terminal screen
(~40 lines). Use fixed-width labels and hyphens for alignment, not tables - the
output will be read in a narrow terminal.

Do not include emojis. Do not include color codes; the calling harness may or
may not interpret them. Plain text, one signal per line.

## What This Command Does Not Do

- It does NOT run tests. The user has the CI for that.
- It does NOT run linters or type-checkers. See `/ce-review` for that pipeline.
- It does NOT dispatch `/ce-review` automatically. Review runs are user-driven.
- It does NOT write any artifact. No session log entry, no checkpoint, no
  .context file. It is a read-only projection of existing state.
- It does NOT enforce anything. `mode:strict` reports a non-zero exit code, but
  the caller decides whether to honor it (e.g. wire it into `/cpm` as a
  pre-merge gate, or leave it advisory).

## Integration Points

- `/cpm` (github-protocols module) can call `/ship-ready mode:strict` before
  initiating the commit/PR/merge flow. Not wired by this command - that
  integration is a separate concern.
- `/ce-review` (ce-review module) provides the envelope files that feed
  section 7. This command reads them; it never writes.
- `learnings-researcher` (compound-knowledge module) provides section 8. If
  absent, section 8 is skipped gracefully.
- Session logging (session-logging module) is not coupled. The dashboard is
  transient.

## Source

Adapted from garrytan/gstack `ship/SKILL.md:667-728` and
`bin/gstack-review-read:1-12`. gstack stores reviews in
`~/.gstack/projects/{slug}/{branch}-reviews.jsonl`. CCGM uses `/ce-review`'s
existing `.context/ce-review/*.json` envelopes as the source of truth instead
of introducing a parallel JSONL store - one log per review pipeline is enough.
gstack's staleness mechanic (store HEAD commit, compare against current HEAD)
is preserved verbatim.
