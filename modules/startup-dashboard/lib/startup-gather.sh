#!/usr/bin/env bash
# startup-gather.sh - Parallel data gathering for /startup command
# Runs all independent checks concurrently and outputs structured sections.
# Called by the /startup agent; not meant to be run manually.

PROJECT_DIR="$PWD"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Identity (synchronous - everything depends on these) ---

WC_MATCH=$(basename "$PWD" | grep -oE 'w[0-9]+-c[0-9]+$' 2>/dev/null || true)
if [ -n "$WC_MATCH" ]; then
  AGENT_ID="agent-${WC_MATCH}"
elif [ -f .env.clone ] && grep -q 'AGENT_ID=' .env.clone 2>/dev/null; then
  AGENT_ID=$(grep 'AGENT_ID=' .env.clone | cut -d= -f2)
else
  AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' 2>/dev/null || echo "0")
  AGENT_ID="agent-${AGENT_NUM}"
fi

# Workspace-root detection: cwd itself isn't a git repo, but child clones exist.
IS_WORKSPACE_ROOT=false
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  for child in "$PWD"/*-c[0-9]*/; do
    if [ -d "$child" ] && git -C "$child" rev-parse --git-dir >/dev/null 2>&1; then
      IS_WORKSPACE_ROOT=true
      break
    fi
  done
fi

# Repo detection: direct if in a git repo, otherwise infer from a child clone.
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename 2>/dev/null | sed 's/\.git$//' || echo "")
if [ -z "$REPO_NAME" ] && [ "$IS_WORKSPACE_ROOT" = true ]; then
  for child in "$PWD"/*-c[0-9]*/; do
    [ -d "$child" ] || continue
    cand=$(git -C "$child" remote get-url origin 2>/dev/null | xargs basename 2>/dev/null | sed 's/\.git$//')
    if [ -n "$cand" ]; then
      REPO_NAME="$cand"
      break
    fi
  done
fi
[ -z "$REPO_NAME" ] && REPO_NAME="unknown"

TODAY=$(date +%Y%m%d)
NOW_TIME=$(date +%H:%M)

# Where to run gh (needs a git-repo cwd). In workspace mode, any child clone works.
GH_CWD="$PROJECT_DIR"
if [ "$IS_WORKSPACE_ROOT" = true ]; then
  for child in "$PWD"/*-c[0-9]*/; do
    if [ -d "$child" ] && git -C "$child" rev-parse --git-dir >/dev/null 2>&1; then
      GH_CWD="${child%/}"
      break
    fi
  done
fi

# --- Parallel jobs (all independent) ---

# 1. Git status + sync (clone mode only; workspace mode emits per-clone summary instead)
(
  cd "$PROJECT_DIR"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "NOT_A_GIT_REPO"
    exit 0
  fi
  BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
  echo "branch:$BRANCH"
  git fetch origin 2>/dev/null
  if git pull origin "$BRANCH" --ff-only 2>/dev/null; then
    echo "sync:ok"
  else
    echo "sync:diverged"
  fi
  AB=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "? ?")
  echo "ahead_behind:$AB"
  echo "---STATUS---"
  git status --short 2>/dev/null
  echo "---COMMITS---"
  git log --oneline -5 2>/dev/null
) > "$TMPDIR/git" 2>/dev/null &

# 1b. Per-clone summary (workspace mode only)
(
  if [ "$IS_WORKSPACE_ROOT" != true ]; then
    exit 0
  fi
  for child in "$PROJECT_DIR"/*-c[0-9]*/; do
    [ -d "$child" ] || continue
    git -C "$child" rev-parse --git-dir >/dev/null 2>&1 || continue
    name=$(basename "$child")
    # Drop the workspace prefix for a compact label (e.g. ccgm-w0-c1 -> c1)
    short=$(echo "$name" | grep -oE 'c[0-9]+$' || echo "$name")
    branch=$(git -C "$child" branch --show-current 2>/dev/null || echo "detached")
    dirty_count=$(git -C "$child" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$dirty_count" = "0" ]; then
      status="clean"
    else
      status="dirty(${dirty_count})"
    fi
    ab=$(git -C "$child" rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "")
    behind=$(echo "$ab" | awk '{print $1}')
    ahead=$(echo "$ab" | awk '{print $2}')
    if [ -z "$ab" ] || { [ "$behind" = "0" ] && [ "$ahead" = "0" ]; }; then
      sync="up to date"
    else
      sync="ahead ${ahead:-0}, behind ${behind:-0}"
    fi
    printf '%s\t%s\t%s\t%s\n' "$short" "$branch" "$status" "$sync"
  done
) > "$TMPDIR/clones" 2>/dev/null &

# 2. Open PRs
(
  cd "$GH_CWD" 2>/dev/null || exit 0
  gh pr list --state open --limit 10 2>/dev/null || echo "none"
) > "$TMPDIR/prs" 2>/dev/null &

# 3. Tracking dashboard (active claims only)
(
  if [ -n "$REPO_NAME" ] && [ "$REPO_NAME" != "unknown" ]; then
    python3 ~/.claude/lib/agent_tracking.py list --repo "$REPO_NAME" 2>/dev/null || echo "unavailable"
  else
    echo "(unknown repo - tracking unavailable)"
  fi
) > "$TMPDIR/tracking" 2>/dev/null &

# 4. Live sessions
(
  python3 ~/.claude/lib/agent_sessions.py --text --exclude-cwd "$PROJECT_DIR" 2>/dev/null || true
) > "$TMPDIR/sessions" 2>/dev/null &

# 5. Sibling branches (clone mode only; workspace mode uses the CLONES section)
(
  if [ "$IS_WORKSPACE_ROOT" = true ]; then
    exit 0
  fi
  cd "$PROJECT_DIR"
  WC=$(basename "$PWD" | grep -oE 'w[0-9]+-c[0-9]+$' 2>/dev/null || true)
  if [ -n "$WC" ]; then
    WS_DIR=$(dirname "$PWD")
    for dir in "$WS_DIR"/*-c[0-9]*/; do
      [ -d "$dir" ] && [ "$dir" != "$PWD/" ] && \
        echo "$(basename "$dir"): $(git -C "$dir" branch --show-current 2>/dev/null)"
    done
  else
    REPOS_DIR=$(dirname "$PWD")
    REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
    for dir in "$REPOS_DIR/${REPO_BASE}"-[0-9]*; do
      [ -d "$dir" ] && [ "$dir" != "$PWD" ] && \
        echo "$(basename "$dir"): $(git -C "$dir" branch --show-current 2>/dev/null)"
    done
  fi
) > "$TMPDIR/siblings" 2>/dev/null &

# 6. Orphan process check
(
  python3 ~/.claude/hooks/orphan-process-check.py 2>/dev/null || true
) > "$TMPDIR/orphans" 2>/dev/null &

# 7. Release check
(
  CURRENT=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  LATEST=$(npm view @anthropic-ai/claude-code version 2>/dev/null || echo "")
  echo "current:${CURRENT:-unknown}"
  echo "latest:${LATEST:-unknown}"
  if [ -n "$CURRENT" ] && [ -n "$LATEST" ] && [ "$CURRENT" != "$LATEST" ]; then
    echo "UPDATE_AVAILABLE"
  fi
) > "$TMPDIR/release" 2>/dev/null &

# 8. Recent activity (7-day session history)
(
  if [ -n "$REPO_NAME" ] && [ "$REPO_NAME" != "unknown" ] && [ -x "$(command -v python3)" ]; then
    python3 "$HOME/.claude/scripts/recall.py" --summary --limit 3 --days 7 2>/dev/null || true
  fi
) > "$TMPDIR/recent" 2>/dev/null &

# 9. Recent merges (last 48h on main)
(
  cd "$GH_CWD" 2>/dev/null || exit 0
  cutoff=$(python3 -c "import datetime; print((datetime.datetime.utcnow()-datetime.timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%SZ'))" 2>/dev/null)
  [ -z "$cutoff" ] && exit 0
  gh pr list --state merged --limit 30 --json number,title,mergedAt,author \
    --jq ".[] | select(.mergedAt > \"$cutoff\") | \"#\\(.number)\\t\\(.mergedAt)\\t\\(.author.login)\\t\\(.title)\"" \
    2>/dev/null || true
) > "$TMPDIR/recent_merges" 2>/dev/null &

# 10a. Priority issues (top 5 open, ordered by priority labels then recency)
(
  cd "$GH_CWD" 2>/dev/null || exit 0
  # Issues with priority labels first, then most recently updated.
  gh issue list --state open --limit 40 --json number,title,labels,updatedAt \
    --jq '[.[] | {n: .number, t: .title, labels: [.labels[].name], u: .updatedAt}]
          | map(. + {priority: (
              if any(.labels[]; . == "p0" or . == "P0" or . == "critical") then 0
              elif any(.labels[]; . == "p1" or . == "P1" or . == "high-priority" or . == "priority") then 1
              elif any(.labels[]; . == "bug") then 2
              elif any(.labels[]; . == "p2" or . == "P2") then 3
              else 4 end)})
          | sort_by(.priority, (.u | split("T")[0] | split("-") | map(tonumber) | (0-.[0]*10000 - .[1]*100 - .[2])))
          | .[0:5]
          | .[] | "#\(.n)\t\((.labels | join(",")) // "")\t\(.t)"' \
    2>/dev/null || true
) > "$TMPDIR/priority_issues" 2>/dev/null &

# 10b. Candidate issues to pick up (open, no linked open PR, not already claimed)
(
  cd "$GH_CWD" 2>/dev/null || exit 0
  # Build set of issue numbers referenced by open PRs (Closes #N / Fixes #N / Resolves #N).
  open_pr_bodies=$(gh pr list --state open --limit 30 --json body,headRefName --jq '.[] | "\(.body) \(.headRefName)"' 2>/dev/null)
  claimed_issues=$(echo "$open_pr_bodies" | grep -oiE '(closes|fixes|resolves) +#[0-9]+' | grep -oE '[0-9]+' | sort -u)
  # Also treat branch names like "123-foo" as a claim on #123.
  branch_claims=$(echo "$open_pr_bodies" | grep -oE '\b[0-9]+-[a-z0-9-]+' | grep -oE '^[0-9]+' | sort -u)
  claimed=$(printf '%s\n%s\n' "$claimed_issues" "$branch_claims" | sort -u | grep -v '^$')
  gh issue list --state open --limit 20 --json number,title,labels \
    --jq '.[] | "\(.number)\t\(.title)"' 2>/dev/null | while IFS=$'\t' read -r n title; do
      if ! echo "$claimed" | grep -qx "$n"; then
        printf '#%s\t%s\n' "$n" "$title"
      fi
    done | head -5
) > "$TMPDIR/candidate_issues" 2>/dev/null &

# Wait for all background jobs
wait

# --- Structured output ---

cat <<GATHER_EOF
=== IDENTITY ===
agent_id:${AGENT_ID}
repo:${REPO_NAME}
date:${TODAY}
time:${NOW_TIME}
project_dir:${PROJECT_DIR}
is_workspace_root:${IS_WORKSPACE_ROOT}

=== GIT ===
$(cat "$TMPDIR/git")

=== CLONES ===
$(cat "$TMPDIR/clones")

=== PRS ===
$(cat "$TMPDIR/prs")

=== TRACKING ===
$(cat "$TMPDIR/tracking")

=== SESSIONS ===
$(cat "$TMPDIR/sessions")

=== SIBLINGS ===
$(cat "$TMPDIR/siblings")

=== ORPHANS ===
$(cat "$TMPDIR/orphans")

=== RELEASE ===
$(cat "$TMPDIR/release")

=== RECENT_ACTIVITY ===
$(cat "$TMPDIR/recent")

=== RECENT_MERGES ===
$(cat "$TMPDIR/recent_merges")

=== CANDIDATE_ISSUES ===
$(cat "$TMPDIR/candidate_issues")

=== PRIORITY_ISSUES ===
$(cat "$TMPDIR/priority_issues")
GATHER_EOF
