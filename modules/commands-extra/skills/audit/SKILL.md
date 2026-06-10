# Codebase Audit

Comprehensive codebase audit. Produces a findings document and creates GitHub issues. Prompts for configuration when invoked.

## Usage

```bash
# Interactive (prompts for configuration)
/audit                    # Asks: scope (read-only vs auto-fix) + execution strategy

# Direct flags (skip the prompt)
/audit --fix              # Audit WITH auto-fixes (uses worktrees, creates PR)
/audit --single           # Single-session audit (one subagent per selected pack, read-only)
/audit --manual           # Set up tasks + output launch commands for manual orchestration
/audit --worker           # Worker mode (run from worktree/clone after --manual setup)
/audit --collect          # Compile results + create issues (after workers complete)
/audit --collect --force  # Collect even if some agents haven't completed
/audit --max-fixes 10     # Limit number of auto-fixes (only with --fix)
```

> **Note on `--single` and `--fix`**: `--single` is always read-only. It never applies
> fixes even if `--fix` is also passed. If you invoke `/audit --single --fix`, the `--fix`
> flag is silently ignored and a note is printed:
> `Note: --single is read-only; --fix ignored. Use parallel-worktrees strategy for auto-fix.`

### Interactive Configuration

When `/audit` is called without flags, it prompts the user with two questions:

1. **Audit scope** - Read-only (just findings) or analyze + auto-fix (also make safe changes, create PR)
2. **Execution strategy** - Parallel worktrees, single session, multi-clone, or manual setup

This ensures the user always knows exactly what the audit will do before it starts.

### Execution Strategies

| Strategy | Agents | Isolation | Depth | Speed |
|----------|--------|-----------|-------|-------|
| **Parallel worktrees** | N workers (one per non-empty assignment) | Git worktrees in `.audit/worktrees/` | Good | Fast |
| **Single session** | One Explore subagent per selected pack | None (all read from same dir) | Light | Fastest |
| **Multi-clone** | N workers | Sibling clone dirs | Deep | Fast |
| **Manual setup** | N full Claude sessions | Worktrees (or clones) | Deepest | Slowest |

---

## CRITICAL: Isolation Rules

1. **Read-only by default** - The audit does NOT modify any files, create branches, or make commits unless the user explicitly chooses "Analyze + auto-fix".
2. **`--single` is always read-only** - It never applies fixes regardless of other flags.
3. **Worktree isolation (recommended)** - When worktrees or auto-fix are used, all work happens in git worktrees under `.audit/worktrees/`. The user's working directory is never touched.
4. **Multi-clone is opt-in only** - Sibling clones are ONLY used when the user explicitly selects "Multi-clone" execution. Before using clones, ALL must be verified as clean (no uncommitted changes, no active feature branches). If any clone has active work, warn the user and suggest worktrees instead.
5. **Always prompt first** - When `/audit` is called without flags, always ask the user to configure scope and execution strategy before doing anything.

---

## Instructions

### Mode Detection & Routing

**If flags are passed, use them directly (skip the interactive prompt):**
- `--single` -> Single-Session Mode (Phases 1-7), always read-only
- `--worker` -> Worker Mode (Phases W1-W5)
- `--collect` -> Collector Mode (Phases C1-C4)
- `--force` -> sets FORCE_COLLECT=true (only used with --collect)
- `--fix` -> sets FIX_MODE=true (ignored silently when combined with --single)
- `--max-fixes N` -> sets MAX_FIXES=N (only with --fix)
- `--manual` -> Coordinator-Only Mode (Phases M1-M4 + output launch commands)
- Remaining argument is the target path (default: entire repo)

**If NO flags are passed, prompt the user with `AskUserQuestion` to configure the audit:**

Use AskUserQuestion with TWO questions:

**Question 1** - header: "Audit scope", question: "What should the audit do?"
Options:
1. **Read-only (Recommended)** - description: "Analyze the codebase, produce a findings report, and create GitHub issues. No code changes."
2. **Analyze + auto-fix** - description: "Same as read-only, plus automatically fix high-confidence issues (unused imports, console.logs, formatting). Creates a PR with fixes for review."

**Question 2** - header: "Execution", question: "How should the audit run?"
Options:
1. **Parallel worktrees (Recommended)** - description: "Task agents in isolated git worktrees within this repo. Good balance of depth and speed. Your working directory is never touched."
2. **Single session** - description: "Lightweight read-only subagents in the current session. One subagent per selected pack. Fastest but least thorough."
3. **Multi-clone** - description: "Agents across sibling clone directories. Deepest analysis with full context per agent. WARNING: Requires all clones to be on clean branches with no active work."
4. **Manual setup** - description: "Set up worktrees and task files, then output launch commands so you can run each agent yourself in separate terminals."

**Map user choices to configuration:**

| Scope | Execution | Result |
|-------|-----------|--------|
| Read-only | Parallel worktrees | Default autonomous mode (M1-M7, FIX_MODE=false) |
| Read-only | Single session | Single-session mode (Phases 1-7, always read-only) |
| Read-only | Multi-clone | Clone-based autonomous mode (M1-M7, FIX_MODE=false, USE_CLONES=true) |
| Read-only | Manual setup | Manual mode (M1-M4 + launch commands) |
| Analyze + auto-fix | Parallel worktrees | Autonomous mode with fixes (M1-M7, FIX_MODE=true) |
| Analyze + auto-fix | Single session | Single-session mode (Phases 1-7, read-only; --fix silently ignored) |
| Analyze + auto-fix | Multi-clone | Clone-based mode with fixes (M1-M7, FIX_MODE=true, USE_CLONES=true) |
| Analyze + auto-fix | Manual setup | Manual mode with fixes (M1-M4 + launch commands, FIX_MODE=true) |

**Multi-clone mode additional validation (when selected):**
Before proceeding, the coordinator MUST:
1. Discover sibling clones by detecting the repo name from `git remote get-url origin` (basename without `.git`) and listing sibling directories matching `{repo-name}-[0-9]*` or `{repo-name}-repos/{repo-name}-[0-9]*` in the parent directory.
2. Verify ALL clones have clean git state (`git status --porcelain` returns empty)
3. Verify NO clone has active feature branches checked out (all should be on the base branch or `main`)
4. If any clone is dirty or has active work, WARN the user and suggest "Parallel worktrees" instead
5. Only proceed after explicit user confirmation

**Derive environment variables:**
```bash
# Repo root (the current working directory where /audit is invoked)
REPO_DIR=$(git rev-parse --show-toplevel)

# Audit coordination directory (inside the repo, gitignored)
AUDIT_DIR="$REPO_DIR/.audit"

# Today's date
AUDIT_DATE=$(date +%Y%m%d)

# Base branch: detect from remote HEAD, fall back to "main"
BASE_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
  | sed 's|refs/remotes/origin/||' \
  || echo "main")
[ -z "$BASE_BRANCH" ] && BASE_BRANCH="main"

# Package manager: detect from lockfile present in repo root
if [ -f "$REPO_DIR/bun.lockb" ]; then
  PKG_MANAGER="bun"
elif [ -f "$REPO_DIR/pnpm-lock.yaml" ]; then
  PKG_MANAGER="pnpm"
elif [ -f "$REPO_DIR/yarn.lock" ]; then
  PKG_MANAGER="yarn"
elif [ -f "$REPO_DIR/package-lock.json" ]; then
  PKG_MANAGER="npm"
else
  PKG_MANAGER="npm"  # safe fallback: npm is always present in Node projects
fi

# Skill root (absolute path to the installed skill directory)
SKILL_ROOT="$HOME/.claude/skills/audit"
```

---

## Autonomous Mode (DEFAULT) (Phases M1-M7)

Run from any clone. The default is **read-only** - no code changes unless `--fix` is passed.

### Phase M1: Pre-Flight

1. **Verify this is a git repo** and identify the repo root:
   ```bash
   REPO_DIR=$(git rev-parse --show-toplevel)
   ```

2. **Ensure `.audit` is gitignored**: Check if `.audit` or `.audit/` is in `.gitignore`. If not, add it:
   ```bash
   grep -qxF '.audit/' .gitignore 2>/dev/null || echo '.audit/' >> .gitignore
   ```
   Do NOT commit this change - it's a local-only addition.

3. **Check for existing audit run**: Look for `$AUDIT_DIR/current/config.json`.
   - If exists, ask the user:
     ```
     An existing audit run was found from [date].
     1. Resume (keep existing task files, only recreate missing ones)
     2. Clean start (move .audit/current/ to .audit/archived-YYYYMMDD/ and start fresh)
     3. Cancel
     ```

4. **Check for open audit PRs** (informational):
   ```bash
   gh pr list --search "Audit:" --state open
   ```
   Warn if existing audit PRs are open.

5. **If --fix mode**: Verify clean git state and check for existing worktrees (see Fix Mode Addendum below).

### Phase M2: Create Coordination Directory

```bash
mkdir -p "$AUDIT_DIR/current/tasks"
mkdir -p "$AUDIT_DIR/current/results"
mkdir -p "$AUDIT_DIR/current/spine"
mkdir -p "$AUDIT_DIR/history"
```

Write `config.json`:
```json
{
  "audit_date": "YYYYMMDD",
  "started_at": "ISO-8601",
  "base_branch": "<detected base branch>",
  "scope": "entire repo",
  "fix_mode": false,
  "repo_dir": "<absolute path to repo root>",
  "epic_issue": null
}
```

### Phase M2.5: Create Epic Issue

Create a GitHub epic issue to serve as the parent tracker for this audit run. All downstream findings issues (created during collection) will reference this epic.

```bash
gh issue create \
  --title "Audit: YYYY-MM-DD - Codebase Audit" \
  --label "audit" \
  --body "$(cat <<'EOF'
## Codebase Audit - YYYY-MM-DD

Tracking issue for the YYYY-MM-DD codebase audit.

### Status
- **Started**: YYYY-MM-DD
- **Mode**: Read-only audit

### Downstream Issues
Pack-specific findings issues will be linked here as they are created.

---
*Generated by `/audit` skill*
EOF
)"
```

Save the epic issue number in `config.json` as `"epic_issue"`.

### Phase M3: Ecosystem Detection + Pack Selection + Pack Assignment

This phase replaces the legacy hardcoded 9-category model with the pack registry pipeline.

1. **Run the ecosystem detector:**
   ```bash
   bash "$SKILL_ROOT/scripts/detect-ecosystems.sh" "$REPO_DIR" \
     > "$AUDIT_DIR/current/detection.json"
   ```

2. **Run the pack registry to select applicable packs:**
   ```bash
   python3 "$SKILL_ROOT/scripts/registry.py" "$AUDIT_DIR/current/detection.json" \
     > "$AUDIT_DIR/current/selected-packs.json"
   ```

3. **HALT if zero packs selected** — do NOT silently proceed:
   ```bash
   PACK_COUNT=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" \
     "$AUDIT_DIR/current/selected-packs.json")
   if [ "$PACK_COUNT" -eq 0 ]; then
     echo "ERROR: registry selected zero packs for this repository." >&2
     echo "  Detection output: $AUDIT_DIR/current/detection.json" >&2
     echo "  Review the detected ecosystems and project shape, then re-run." >&2
     exit 1
   fi
   ```

4. **Run the pack assignment balancer** (default 4 workers):
   ```bash
   python3 "$SKILL_ROOT/scripts/assign-packs.py" \
     "$AUDIT_DIR/current/selected-packs.json" \
     --workers 4 \
     > "$AUDIT_DIR/current/assignment.json"
   ```
   The assignment maps worker ids 0..N-1 to ordered pack-id lists.
   Workers with empty lists will NOT be launched (see M5).

5. **Prepare agent environment** (worktree/clone/none per strategy — same as before):

   **Worktree mode:**
   ```bash
   git fetch origin
   mkdir -p "$AUDIT_DIR/worktrees"
   for i in 0 1 2 3; do
     git worktree add "$AUDIT_DIR/worktrees/agent-$i" \
       -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
   done
   ```
   If FIX_MODE is true, install dependencies in each worktree using the detected package manager.

   **Multi-clone mode:**
   ```bash
   REPOS_DIR=$(dirname "$REPO_DIR")
   REPO_BASE=$(git remote get-url origin 2>/dev/null | sed 's|.*/||; s|\.git$||')
   if [ -z "$REPO_BASE" ]; then
     REPO_BASE=$(basename "$REPO_DIR" | sed -E 's/-[0-9]+$//')
   fi
   CLONE_DIRS=()
   for i in 0 1 2 3; do
     candidate="$REPOS_DIR/${REPO_BASE}-$i"
     [ -d "$candidate/.git" ] || [ -f "$candidate/.git" ] && CLONE_DIRS+=("$candidate")
   done
   if [ "${#CLONE_DIRS[@]}" -eq 0 ]; then
     echo "ERROR: Multi-clone discovery found zero sibling clone directories." >&2
     echo "  Searched: $REPOS_DIR/${REPO_BASE}-{0..3}" >&2
     echo "  Suggest: use 'Parallel worktrees' mode instead." >&2
     exit 1
   fi
   for dir in "${CLONE_DIRS[@]}"; do
     git -C "$dir" status --porcelain
   done
   ```
   Verify all clones are clean. Create audit branches in each clone.

   **Single-session mode:** No preparation needed. Skip to M4.

### Phase M4: Run Spine + Write Task Files

**Run the deterministic spine** (coordinator responsibility, once per audit run):
```bash
# Compute union of tools[] across all selected packs
SPINE_TOOLS=$(python3 - "$AUDIT_DIR/current/selected-packs.json" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
tools = set()
for p in packs:
    tools.update(p.get("tools", []))
print(",".join(sorted(tools)) if tools else "")
PYEOF
)

mkdir -p "$AUDIT_DIR/current/spine"

if [ -z "$SPINE_TOOLS" ]; then
  echo "Note: no selected packs declare tools[]; skipping spine run." >&2
  touch "$AUDIT_DIR/current/spine/findings.jsonl"
else
  bash "$SKILL_ROOT/scripts/spine/run.sh" \
    --repo  "$REPO_DIR" \
    --tools "$SPINE_TOOLS" \
    --output "$AUDIT_DIR/current/spine/findings.jsonl"
fi
```

**Slice the spine output per pack:**

For each selected pack, filter `spine/findings.jsonl` to produce a per-pack slice.
A finding belongs in a pack's slice when any of these is true:
  - The finding's `check_id` namespace (the part before `/`) matches a check-id prefix declared
    in the pack's `checks` array (e.g. pack has check `"id": "security/leaked-credential"` → the
    `security` namespace matches findings with `check_id` starting with `security/`).
  - The finding's `properties.tool` value (where spine normalizers store the tool name — e.g.
    `parse-gitleaks.py` emits `{"properties": {"tool": "gitleaks"}}`) matches a tool listed in
    the pack's `tools[]`. There is no top-level `tool` field on findings.
  - The finding has no `properties.tool` value (un-attributed): assign it to ALL packs that
    declare at least one tool (broad assignment to avoid silent gaps).

```bash
python3 - \
  "$AUDIT_DIR/current/spine/findings.jsonl" \
  "$AUDIT_DIR/current/selected-packs.json" \
  "$AUDIT_DIR/current/spine" << 'PYEOF'
import json, os, sys
spine_file, packs_file, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]

packs = json.load(open(packs_file))

# Build per-pack filtering criteria
pack_criteria = {}
for p in packs:
    pack_dir = p["id"].split("/")[-1]   # e.g. "ccgm/security" -> "security"
    namespaces = set()
    tools = set(p.get("tools", []))
    for check in p.get("checks", []):
        ns = check["id"].split("/")[0]
        namespaces.add(ns)
    pack_criteria[pack_dir] = {"namespaces": namespaces, "tools": tools}

# Any-tool packs (packs that declare at least one tool)
any_tool_packs = {d for d, c in pack_criteria.items() if c["tools"]}

lines = []
try:
    with open(spine_file) as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
except FileNotFoundError:
    pass  # empty spine

for pack_dir, criteria in pack_criteria.items():
    slice_path = os.path.join(out_dir, f"{pack_dir}.jsonl")
    with open(slice_path, "w") as out:
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip non-finding records (provenance, coverage_gap type records)
            if "type" in rec:
                continue
            check_id = rec.get("check_id", "")
            # Spine normalizers store the tool name in properties.tool
            # (e.g. parse-gitleaks.py emits {"properties": {"tool": "gitleaks"}}).
            # Findings have no top-level "tool" field.
            props_tool = rec.get("properties", {}).get("tool", "")
            ns = check_id.split("/")[0] if "/" in check_id else ""

            if ns in criteria["namespaces"]:
                out.write(line + "\n")
            elif props_tool and props_tool in criteria["tools"]:
                out.write(line + "\n")
            elif not props_tool and any_tool_packs:
                # Un-attributed: broadcast to all tool-using packs
                if pack_dir in any_tool_packs:
                    out.write(line + "\n")
PYEOF
```

**Write task files:** For each worker with a non-empty pack assignment:

```bash
python3 - \
  "$AUDIT_DIR/current/assignment.json" \
  "$AUDIT_DIR/current/selected-packs.json" \
  "$SKILL_ROOT" \
  "$AUDIT_DIR" \
  "$REPO_DIR" \
  "${FIX_MODE:-false}" << 'PYEOF'
import json, os, sys
assignment_file, packs_file, skill_root, audit_dir, repo_dir, fix_mode_str = sys.argv[1:]
FIX_MODE = fix_mode_str.lower() in ("true", "1", "yes")

assignment = json.load(open(assignment_file))
all_packs = {p["id"]: p for p in json.load(open(packs_file))}

tasks_dir = os.path.join(audit_dir, "current", "tasks")
os.makedirs(tasks_dir, exist_ok=True)
results_dir = os.path.join(audit_dir, "current", "results")
os.makedirs(results_dir, exist_ok=True)

rubric_path = os.path.join(skill_root, "schemas", "severity-rubric.json")
try:
    rubric = json.load(open(rubric_path))
    # Extract rubric check-ids for this worker's packs
except Exception:
    rubric = {}

for worker_id, pack_ids in assignment.items():
    if not pack_ids:
        continue  # skip empty workers

    # Build rubric slice for this worker's packs
    worker_check_ids = set()
    for pid in pack_ids:
        p = all_packs.get(pid, {})
        for check in p.get("checks", []):
            worker_check_ids.add(check["id"])

    rubric_slice = {}
    if isinstance(rubric, dict):
        rubric_checks = rubric.get("checks", rubric)  # unwrap top-level "checks" key
        for cid, val in rubric_checks.items():
            if cid in worker_check_ids:
                rubric_slice[cid] = val

    packs_info = []
    for pid in pack_ids:
        p = all_packs.get(pid, {})
        pack_dir = pid.split("/")[-1]
        checks_path = os.path.join(skill_root, "packs", pack_dir, "checks.md")
        spine_slice = os.path.join(audit_dir, "current", "spine", f"{pack_dir}.jsonl")
        packs_info.append({
            "pack_id": pid,
            "checks_md_path": checks_path,
            "spine_slice_path": spine_slice,
        })

    results_path = os.path.join(audit_dir, "current", "results", f"worker-{worker_id}.json")

    task = {
        "worker_id": worker_id,
        "packs": packs_info,
        "rubric_slice": rubric_slice,
        "results_file_path": results_path,
        "repo_dir": repo_dir,
        "fix_mode": FIX_MODE,   # passed in from the coordinator — True when --fix was selected
    }

    task_path = os.path.join(tasks_dir, f"worker-{worker_id}.json")
    with open(task_path, "w") as f:
        json.dump(task, f, indent=2)
    print(f"Wrote {task_path}")
PYEOF
```

### Phase M5: Launch Audit Workers

**CRITICAL**: Determine which workers have non-empty pack assignments, then launch only those workers — in a SINGLE message with parallel Task tool calls (`subagent_type: "general-purpose"`, `run_in_background: true`).

```bash
# Determine active worker ids
ACTIVE_WORKERS=$(python3 -c "
import json, sys
a = json.load(open(sys.argv[1]))
print(' '.join(k for k,v in sorted(a.items()) if v))
" "$AUDIT_DIR/current/assignment.json")
```

Display progress summary before launching:
```
## Launching Audit Workers

| Worker | Packs | Working Dir | Mode |
|--------|-------|------------|------|
| 0 | <pack-ids> | {agent_dir} | {mode} |
...

Running {N} audit workers in parallel...
```

**Prompt template for each Task agent (read-only mode):**

```
You are audit worker {WORKER_ID} performing a READ-ONLY codebase audit using the pack registry.

CODEBASE ROOT: {AGENT_WORKING_DIR}
TASK FILE: {AUDIT_DIR}/current/tasks/worker-{WORKER_ID}.json
RESULTS FILE: {AUDIT_DIR}/current/results/worker-{WORKER_ID}.json

IMPORTANT: This is a READ-ONLY audit. Do NOT modify any source files. Do NOT create branches or make commits.
Use ABSOLUTE PATHS for ALL file operations. Your codebase root is {AGENT_WORKING_DIR}.

## Instructions

1. Read your task file to get your assigned pack ids, checks.md paths, spine slice path, and rubric slice.

2. Write an initial results file to signal you've started:
   Write {"worker_id": "{WORKER_ID}", "status": "in_progress", "started_at": "<ISO timestamp>"}

3. For each assigned pack:
   a. Read the pack's checks.md from the absolute path in your task file.
   b. Run each check described in checks.md against the codebase.
   c. For findings with detection="hybrid" in your spine slice: triage (confirmed/dismissed).
      A finding should be confirmed if your LLM analysis agrees it is a real issue.
      Dismissed means you are confident it is a false positive.
   d. Add any LLM-only findings with source:"llm".
   e. Source all severity/confidence/fix_confidence from the rubric_slice in your task file.
      For check_ids not in the rubric, set confidence:"low" and flag for rubric expansion.

4. Write final results to your results file per the worker results-file contract.

Be thorough. Read entire files when needed. Trace patterns across the codebase. This is a deep audit.
```

After launching all workers, poll for completion using TaskOutput. Once all active workers complete (or timeout), proceed to Phase M6.

### Phase M6: Merge Findings + Compile Report

After all workers complete:

1. **Run the merge pipeline:**
   ```bash
   # Collect all worker result files (array — safe for paths with spaces)
   LLM_ARGS=()
   for f in "$AUDIT_DIR/current/results"/worker-*.json; do
     LLM_ARGS+=(--llm "$f")
   done

   python3 "$SKILL_ROOT/scripts/merge-findings.py" \
     --spine  "$AUDIT_DIR/current/spine/findings.jsonl" \
     "${LLM_ARGS[@]}" \
     --rubric "$SKILL_ROOT/schemas/severity-rubric.json" \
     --repo   "$REPO_DIR" \
     --output "$AUDIT_DIR/current/findings.jsonl"
   ```

2. **Compile the audit document** from `$AUDIT_DIR/current/findings.jsonl`:

```markdown
# Codebase Audit Report - YYYY-MM-DD

## Summary

| Metric | Count |
|--------|-------|
| Total Findings | X |
| Critical | X |
| High | X |
| Medium | X |
| Low | X |

## Findings by Pack

| Pack | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| security | X | X | X | X | X |
| dependencies | X | X | X | X | X |
| code-quality | X | X | X | X | X |
...

## Critical & High Severity Findings

### security
- **[security/leaked-credential]** (CRITICAL) ...

### code-quality
...

## Medium Severity Findings
...

## Low Severity Findings
...

## Coverage Gaps

Tools that were absent, wrappers that were skipped, or checks that could not run:

| Tool | Reason |
|------|--------|
| <tool> | <description from coverage_gap record> |

---
*Generated by `/audit` skill on YYYY-MM-DD*
```

3. **Write** the compiled document to `$AUDIT_DIR/current/audit-report.md`.
4. **Display** the summary table and critical/high findings to the user.

### Phase M7: Issue Creation

Ask the user:
```
The audit found {N} findings (Critical: X, High: Y, Medium: Z, Low: W).
Full report: .audit/current/audit-report.md

Would you like me to create GitHub issues for these?
1. Create issues for Critical + High severity only
2. Create issues for all findings
3. Create issues for Critical + High, plus one umbrella issue for Medium + Low
4. Skip issue creation
```

**If creating issues:**

1. Check for existing audit issues: `gh issue list --label "audit" --state open`

2. Create labels if needed:
   ```bash
   gh label create "audit" --color "d4c5f9" 2>/dev/null || true
   gh label create "needs-human-review" --color "fbca04" 2>/dev/null || true
   ```

3. Group findings by pack and create one issue per pack (for selected severity levels).

4. Use the issue template from `reference/output-template.md`.

5. **Link each issue to the epic**: Add `Parent: #<epic_issue>` in the issue body.

6. **Update the epic issue** with downstream issue links.

7. **Optionally clean up**: Ask user if they want to keep `.audit/current/` (for reference) or archive it.

---

### Phase M5-manual: Output Launch Instructions (--manual mode only)

**This phase only runs when `--manual` flag is provided.** It replaces M5-M7 above.

For `--manual` mode, worktrees are always created (even in read-only mode) so each Claude Code session has its own working directory:

```bash
for i in 0 1 2 3; do
  git worktree add "$AUDIT_DIR/worktrees/agent-$i" -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done
```

Display a clear summary and, for each active worker id (those with a non-empty pack assignment),
output the exact launch command block so the user can copy-paste into separate terminals:

```
## Audit Setup Complete — Manual Launch Required

Run each of the following commands in a separate Claude Code terminal:

--- Worker 0 ---
cd {AUDIT_DIR}/worktrees/agent-0
/audit --worker --task {AUDIT_DIR}/current/tasks/worker-0.json
# (worktree strategy) No push needed — the coordinator merges local refs.
# (multi-clone strategy only) After worker finishes: git push origin audit/agent-0-{AUDIT_DATE}

--- Worker 1 ---
cd {AUDIT_DIR}/worktrees/agent-1
/audit --worker --task {AUDIT_DIR}/current/tasks/worker-1.json
# (worktree strategy) No push needed — the coordinator merges local refs.
# (multi-clone strategy only) After worker finishes: git push origin audit/agent-1-{AUDIT_DATE}

... (omit workers with empty pack assignments)

After all workers complete, run from the repo root:
/audit --collect
```

Notes:
- For the **worktree strategy** (default): do NOT push — workers commit to their local audit branch
  and the coordinator merges local refs directly in M6-fix.
- For the **multi-clone strategy**: the `git push origin` step is required — the coordinator merges
  from origin refs and cannot see the branch without the push.

---

## Worker Mode: `--worker` (Phases W1-W5)

Run from a worktree (manual mode) or invoked as a Task agent (autonomous mode). Reads its pack-based task file and performs the audit of assigned packs.

### Phase W1: Self-ID & Task Load

1. **Derive worker id** from current directory or environment.

2. **Derive AUDIT_DIR** from git common directory:
   ```bash
   GIT_COMMON=$(git rev-parse --git-common-dir)
   REPO_ROOT=$(dirname "$GIT_COMMON")
   AUDIT_DIR="$REPO_ROOT/.audit"
   ```

3. **Read task file**:
   ```bash
   cat "$AUDIT_DIR/current/tasks/worker-${WORKER_ID}.json"
   ```
   If task file doesn't exist, error out with a message pointing to `/audit`.

### Phase W2: Init Results File

Write initial results file to signal this worker has started:
```json
{
  "worker_id": "<id>",
  "status": "in_progress",
  "started_at": "ISO-8601",
  "completed_at": null,
  "findings": [],
  "spine_triage": []
}
```

Write to the absolute path from `task.results_file_path`.

### Phase W3: Pack Audit + Spine Triage

For each pack assigned in the task file:

1. **Read the pack's checks.md** from the absolute path `task.packs[N].checks_md_path`.
2. **Read the pack's spine slice** from the absolute path `task.packs[N].spine_slice_path`.
3. **Run the checks** described in checks.md against the codebase (using Grep, Glob, Read with absolute paths).
4. **Triage hybrid candidates**: for every finding in the spine slice with `detection: "hybrid"`,
   decide `confirmed` or `dismissed` and add a `spine_triage` entry:
   - `confirmed`: LLM analysis agrees the finding is real.
   - `dismissed`: LLM is confident it is a false positive.
   - A finding is only dropped if ALL workers that named its fingerprint voted `dismissed`
     (the merge step enforces unanimity).
5. **Add LLM-only findings** with `source: "llm"`.
6. **Source all severity/confidence/fix_confidence from `task.rubric_slice`**. For check_ids not
   in the rubric slice, set `confidence: "low"` and note for rubric expansion.

Workers must NOT invent severity from intuition. Use the rubric only.

### Phase W4: Fix Cycle (--fix mode only)

**Skip entirely unless FIX_MODE is true (from task file).**

See "Fix Mode Addendum" below for the full fix cycle.
Auto-fix eligibility requires BOTH: the pack's `auto_fixable: true` flag AND the rubric's
`fix_confidence` being `"high"` OR `"medium"`. See the **Auto-Fix Confidence Reference** section
for the complete rule. `"high"` checks are auto-applied without extra checks; `"medium"` checks
are attempted with extra verification steps before committing. All others (`"low"`) are flagged
for human review and never auto-applied.

### Phase W5: Write Final Results

Write the results file to the absolute path from `task.results_file_path`:

```json
{
  "worker_id": "<id>",
  "status": "completed",
  "started_at": "ISO-8601",
  "completed_at": "ISO-8601",
  "findings": [
    {
      "check_id":      "<pack-dir>/<check-id-suffix>",
      "severity":      "critical|high|medium|low|info",
      "confidence":    "high|medium|low",
      "detection":     "llm|hybrid",
      "source":        "llm",
      "message":       "<human-readable description>",
      "location":      {"path": "<repo-relative path>", "line": 1},
      "fix_confidence":"high|medium|low"
    }
  ],
  "spine_triage": [
    {
      "fingerprint": "<fingerprint from spine slice>",
      "verdict":     "confirmed|dismissed",
      "note":        "<optional explanation>"
    }
  ]
}
```

Display completion summary:
```
## Worker {N} Audit Complete

Packs: [list]
Findings: X (Critical: X, High: X, Medium: X, Low: X)
Spine triage: X confirmed, X dismissed
```

---

## Collector Mode: `--collect` (Phases C1-C4)

Run from the repo root (NOT from a worktree) after all workers complete. Compiles results and creates issues.

### Phase C1: Verify Completion

Check all result files listed in `assignment.json`:
```bash
python3 -c "
import json, sys, os
a = json.load(open(sys.argv[1]))
audit_dir = sys.argv[2]
for wid, packs in sorted(a.items()):
    if not packs:
        continue
    rf = os.path.join(audit_dir, 'current', 'results', f'worker-{wid}.json')
    try:
        status = json.load(open(rf)).get('status', 'missing')
    except Exception:
        status = 'no file'
    print(f'Worker {wid}: {status}')
" "$AUDIT_DIR/current/assignment.json" "$AUDIT_DIR"
```

- If all active workers show `"completed"`, proceed.
- If any show `"in_progress"` or `"missing"`:
  - Without `--force`: Report status and wait.
  - With `--force`: Warn and proceed with available results.

### Phase C2: Merge + Compile Report

Run the merge pipeline (same as Phase M6 above) and compile the pack-grouped audit report with Coverage Gaps section.

**Merge conflict handling (--fix only):** If a git merge step produces conflicts:

1. **Capture the conflicted files first** — before aborting, record the evidence:
   ```bash
   CONFLICT_REPORT="$AUDIT_DIR/current/merge-conflicts.md"
   CONFLICTED_FILES=$(git diff --name-only --diff-filter=U)
   cat >> "$CONFLICT_REPORT" <<EOF
   ## Merge conflict

   Conflicted files (captured before abort):
   $CONFLICTED_FILES

   Resolution required: Manually review and resolve conflicts, then re-run --collect.
   EOF
   ```
2. **Then abort the merge**:
   ```bash
   git merge --abort 2>/dev/null || true
   ```
3. **HALT** with message:
   "MERGE CONFLICT on worker branch. See $CONFLICT_REPORT. Resolve manually then re-run --collect."

The conflict report is written BEFORE the abort so the file list is preserved.
After `git merge --abort` the conflict markers are gone — the report is the only record.

### Phase C3: Issue Creation

Same as Phase M7 above — present the report, ask about issue creation.

### Phase C4: Archive & Cleanup

1. **Archive results**: Write `history/YYYYMMDD.json` per the schema in `reference/multi-agent-config.md`.

2. **If worktrees exist**, clean them up:
   ```bash
   for i in 0 1 2 3; do
     git worktree remove "$AUDIT_DIR/worktrees/agent-$i" --force 2>/dev/null || true
   done
   git worktree prune
   ```

3. **If multi-clone mode was used**, reset clones to base branch.

4. **Delete remote agent branches** (if they were pushed in fix mode).

5. **Ask about cleanup**: Keep or archive `.audit/current/`.

---

## Fix Mode Addendum (--fix)

When `--fix` is passed, these additional steps are added to the workflow.
`--fix` is silently ignored when combined with `--single`.

### M3-fix: Create Worktrees

```bash
git fetch origin
for i in 0 1 2 3; do
  git worktree add "$AUDIT_DIR/worktrees/agent-$i" -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done

# Install dependencies in each worktree (parallel) using the detected package manager
case "$PKG_MANAGER" in
  bun)  INSTALL_CMD="bun install --frozen-lockfile" ;;
  pnpm) INSTALL_CMD="pnpm install --frozen-lockfile" ;;
  yarn) INSTALL_CMD="yarn install --frozen-lockfile" ;;
  *)    INSTALL_CMD="npm ci" ;;
esac
for i in 0 1 2 3; do
  (cd "$AUDIT_DIR/worktrees/agent-$i" && $INSTALL_CMD 2>&1 | tail -1) &
done
wait
```

### M5-fix: Worker Prompts Include Fix Instructions

The Task agent prompts are extended with strategy-specific instructions:

**Worktree strategy** (default `--fix` path):
```
WORKING DIRECTORY: {AUDIT_DIR}/worktrees/agent-{N}
Use `git -C {AUDIT_DIR}/worktrees/agent-{N}` for all git commands.

For auto-fixable findings (rubric fix_confidence=high AND pack check auto_fixable=true):
- Implement fixes using Edit tool with absolute paths
- Run verification using commands from the verification_commands field
- If verification passes: git add <files> && git commit -m "audit(<pack>): <title>"
- If verification fails: git checkout -- . && git clean -fd
- Record fix success/failure in results

IMPORTANT (worktree strategy): When finished, commit your changes to your audit branch.
Do NOT push — your branch is a LOCAL ref (audit/agent-{N}-{DATE}). The coordinator
merges it directly from local refs. Pushing is not needed and not expected.
```

**Multi-clone strategy** (`--fix` with USE_CLONES=true):
```
WORKING DIRECTORY: {CLONE_DIR}
Use git commands within {CLONE_DIR}.

For auto-fixable findings (rubric fix_confidence=high AND pack check auto_fixable=true):
- Implement fixes using Edit tool with absolute paths
- Run verification using commands from the verification_commands field
- If verification passes: git add <files> && git commit -m "audit(<pack>): <title>"
- If verification fails: git checkout -- . && git clean -fd
- Record fix success/failure in results

IMPORTANT (multi-clone strategy): When finished, push your branch:
  git push origin audit/agent-{N}-{DATE}
The coordinator merges origin refs (not local), so the push is required.
```

### W4-fix: Fix Cycle

For each auto-fixable finding (rubric `fix_confidence: "high"` AND pack check `auto_fixable: true`),
ordered by fix_confidence (high first, then medium):

1. **Implement the fix** using Edit/Write tools
2. **Run verification** using verification commands from the task file
3. **If verification passes**: Commit
4. **If verification fails**: Revert and continue to next finding
5. Stop if MAX_FIXES reached.

### M6-fix: Merge & Create PR

After collecting results, merge the fix branches into a combined branch, verify, push, and create a PR targeting `$BASE_BRANCH`.

The merge strategy differs by execution mode:

**Worktree strategy** (default): worker branches are LOCAL refs in the main repo's ref namespace
(worktrees share refs with the main checkout). Merge them directly — no push required from workers.

**Multi-clone strategy**: worker branches live in separate repos and were pushed to origin.
Merge from `origin/audit/agent-$i-$AUDIT_DATE`.

1. **Create collector worktree**:
   ```bash
   git worktree add "$AUDIT_DIR/worktrees/combined" -b "audit/$AUDIT_DATE" "origin/$BASE_BRANCH"
   ```

2. **Merge each worker branch** in order (worker-0 first, ascending).
   **CRITICAL: merge conflicts HALT the process — do NOT auto-resolve with `--ours`.**
   ```bash
   cd "$AUDIT_DIR/worktrees/combined"
   CONFLICT_REPORT="$AUDIT_DIR/current/merge-conflicts.md"
   MERGE_OK=true
   MERGED_COUNT=0
   EXPECTED_BRANCHES=()

   for i in 0 1 2 3; do
     EXPECTED_BRANCHES+=("audit/agent-$i-$AUDIT_DATE")
   done

   if [ "${USE_CLONES:-false}" = "true" ]; then
     # Multi-clone: branches were pushed to origin — merge from origin refs
     for i in 0 1 2 3; do
       BRANCH="origin/audit/agent-$i-$AUDIT_DATE"
       git rev-parse --verify --quiet "origin/audit/agent-$i-$AUDIT_DATE" 2>/dev/null || continue
       if ! git merge "$BRANCH" --no-edit 2>/dev/null; then
         MERGE_OK=false
         CONFLICTED_FILES=$(git diff --name-only --diff-filter=U)
         cat >> "$CONFLICT_REPORT" <<EOF
## Merge conflict: agent-$i branch

Conflicted files (captured before abort):
$CONFLICTED_FILES

Resolution required: Manually review and resolve conflicts between
the already-merged branches and audit/agent-$i-$AUDIT_DATE.
EOF
         git merge --abort 2>/dev/null || true
         echo "MERGE CONFLICT on agent-$i branch. See $CONFLICT_REPORT"
         echo "STOPPING: resolve conflicts manually then re-run --collect."
         break
       fi
       MERGED_COUNT=$((MERGED_COUNT + 1))
     done
   else
     # Worktree strategy: branches are local refs — no push needed from workers
     for i in 0 1 2 3; do
       BRANCH="audit/agent-$i-$AUDIT_DATE"
       git rev-parse --verify --quiet "$BRANCH" 2>/dev/null || continue
       if ! git merge "$BRANCH" --no-edit 2>/dev/null; then
         MERGE_OK=false
         CONFLICTED_FILES=$(git diff --name-only --diff-filter=U)
         cat >> "$CONFLICT_REPORT" <<EOF
## Merge conflict: agent-$i branch

Conflicted files (captured before abort):
$CONFLICTED_FILES

Resolution required: Manually review and resolve conflicts between
the already-merged branches and audit/agent-$i-$AUDIT_DATE.
EOF
         git merge --abort 2>/dev/null || true
         echo "MERGE CONFLICT on agent-$i branch. See $CONFLICT_REPORT"
         echo "STOPPING: resolve conflicts manually then re-run --collect."
         break
       fi
       MERGED_COUNT=$((MERGED_COUNT + 1))
     done
   fi

   if [ "$MERGE_OK" != "true" ]; then
     echo "Merge incomplete. Review $CONFLICT_REPORT before proceeding."
     exit 1
   fi

   # Zero-merge guard: if fix mode ran but NO branches merged, halt loudly
   if [ "$MERGED_COUNT" -eq 0 ]; then
     echo "ERROR: Fix mode ran but ZERO worker branches were merged." >&2
     echo "  Expected branches:" >&2
     for b in "${EXPECTED_BRANCHES[@]}"; do echo "    $b" >&2; done
     echo "  No combined branch was pushed and no PR was created." >&2
     echo "  Possible causes: workers did not commit, wrong AUDIT_DATE, or branches" >&2
     echo "  were removed before M6-fix ran." >&2
     exit 1
   fi
   ```

   If `MERGED_COUNT` is less than the number of active workers, continue but include a note
   in the PR body listing which branches were merged and which were missing.

3. **Install deps and verify** using the detected package manager:
   ```bash
   $INSTALL_CMD
   ${LINT_CMD:-true} && ${TYPECHECK_CMD:-true} && ${BUILD_CMD:-true}
   ```

4. **Push and create PR**:
   ```bash
   git push origin "audit/$AUDIT_DATE"
   gh pr create \
     --title "Audit fixes: $AUDIT_DATE" \
     --body "Auto-fixes from /audit --fix run on $AUDIT_DATE. Review each commit.
Merged $MERGED_COUNT of ${#EXPECTED_BRANCHES[@]} worker branches." \
     --base "$BASE_BRANCH"
   ```

---

## Single-Session Mode: `--single` (Phases 1-7)

**Always read-only.** If invoked with `--fix`, print:
```
Note: --single is read-only; --fix ignored. Use parallel-worktrees strategy for auto-fix.
```
Then proceed as read-only.

Dispatches one read-only Explore subagent per **selected pack** (not a fixed 9) after running
the detector, registry, spine, and merge scripts inline.

### Phase 1: Pre-Flight

Parse arguments. Verify git repo. Set up `REPO_DIR`, `AUDIT_DIR`, `SKILL_ROOT`.

```bash
REPO_DIR=$(git rev-parse --show-toplevel)
AUDIT_DIR="$REPO_DIR/.audit"
SKILL_ROOT="$HOME/.claude/skills/audit"
mkdir -p "$AUDIT_DIR/current/spine"
mkdir -p "$AUDIT_DIR/current/results"
grep -qxF '.audit/' .gitignore 2>/dev/null || echo '.audit/' >> .gitignore
```

### Phase 2: Ecosystem Detection + Pack Selection

Run the detector and registry inline:

```bash
bash "$SKILL_ROOT/scripts/detect-ecosystems.sh" "$REPO_DIR" \
  > "$AUDIT_DIR/current/detection.json"

python3 "$SKILL_ROOT/scripts/registry.py" "$AUDIT_DIR/current/detection.json" \
  > "$AUDIT_DIR/current/selected-packs.json"

PACK_COUNT=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" \
  "$AUDIT_DIR/current/selected-packs.json")

if [ "$PACK_COUNT" -eq 0 ]; then
  echo "ERROR: registry selected zero packs for this repository." >&2
  exit 1
fi
```

### Phase 3: Run the Spine Inline

Compute the union of tools from selected packs and run the spine:

```bash
SPINE_TOOLS=$(python3 - "$AUDIT_DIR/current/selected-packs.json" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
tools = set()
for p in packs:
    tools.update(p.get("tools", []))
print(",".join(sorted(tools)) if tools else "")
PYEOF
)

if [ -z "$SPINE_TOOLS" ]; then
  echo "Note: no selected packs declare tools[]; skipping spine run." >&2
  touch "$AUDIT_DIR/current/spine/findings.jsonl"
else
  bash "$SKILL_ROOT/scripts/spine/run.sh" \
    --repo  "$REPO_DIR" \
    --tools "$SPINE_TOOLS" \
    --output "$AUDIT_DIR/current/spine/findings.jsonl"
fi
```

Then produce per-pack spine slices using the same slicing logic as Phase M4.

### Phase 4: Dispatch Read-Only Pack Subagents

Launch **one Task agent per SELECTED pack** (not a fixed 9) in a SINGLE message with parallel
Task tool calls (`subagent_type: "Explore"`, `run_in_background: true`).

For each pack, the subagent receives:
- The absolute path to the pack's `checks.md` (`$SKILL_ROOT/packs/<pack-dir>/checks.md`)
- The rubric slice for this pack's check-ids
- The absolute path to the pack's spine slice (`$AUDIT_DIR/current/spine/<pack-dir>.jsonl`)
- The absolute results-file path (`$AUDIT_DIR/current/results/single-<pack-dir>.json`)
- Instruction to write results per the worker results-file contract

**Prompt template for each Explore subagent:**

```
You are a read-only pack auditor for the '{PACK_ID}' pack.

CODEBASE ROOT: {REPO_DIR}
CHECKS FILE: {CHECKS_MD_PATH}
SPINE SLICE: {SPINE_SLICE_PATH}
RESULTS FILE: {RESULTS_FILE_PATH}
RUBRIC SLICE: {RUBRIC_SLICE_JSON}

IMPORTANT: READ-ONLY. Do NOT modify files, create branches, or make commits.

1. Read the checks.md from CHECKS FILE.
2. Read the spine slice from SPINE SLICE.
3. Run each check from checks.md against the codebase using Grep, Glob, Read.
4. For each "hybrid" detection finding in the spine slice: triage as confirmed/dismissed.
5. Add any LLM-only findings with source:"llm".
6. Source severity/confidence/fix_confidence from RUBRIC SLICE only.
7. Write results to RESULTS FILE per the worker results-file contract.
```

### Phase 5: Run Merge Inline

After all subagents complete, run the merge pipeline:

```bash
# Collect single-session result files (array — safe for paths with spaces)
LLM_ARGS=()
for f in "$AUDIT_DIR/current/results"/single-*.json; do
  [ -f "$f" ] && LLM_ARGS+=(--llm "$f")
done

python3 "$SKILL_ROOT/scripts/merge-findings.py" \
  --spine  "$AUDIT_DIR/current/spine/findings.jsonl" \
  "${LLM_ARGS[@]}" \
  --rubric "$SKILL_ROOT/schemas/severity-rubric.json" \
  --repo   "$REPO_DIR" \
  --output "$AUDIT_DIR/current/findings.jsonl"
```

### Phase 6: Compile Report + Display Summary

Compile the pack-grouped audit report from `$AUDIT_DIR/current/findings.jsonl` — same format
as Phase M6, including the **Coverage Gaps** section. Write to `$AUDIT_DIR/current/audit-report.md`.

Display the summary table and critical/high findings to the user.

### Phase 7: Optional Issue Creation + Cleanup

Ask about issue creation (same as Phase M7, except `--single` never creates an epic issue —
it creates standalone issues with no `Parent:` link and no epic-update step). Ask about cleanup.
Archive results.

---

## Auto-Fix Confidence Reference

Auto-fix eligibility is keyed off both the rubric's `fix_confidence` AND the pack's `auto_fixable`
flag on the specific check. A check is eligible for autonomous fix only when:
- The pack's check entry has `"auto_fixable": true`, AND
- The rubric's `fix_confidence` for that `check_id` is `"high"` or `"medium"`.

### HIGH Confidence (auto-fix with --fix)
- `eslint --fix` for fixable rules
- `prettier --write` for formatting
- `npm audit fix` (non-breaking only)
- Remove unused imports/variables
- Add missing semicolons

### MEDIUM Confidence (fix with extra care)
- Add explicit return types (verify inference is correct)
- Replace simple `any` with inferred type
- Add React.memo wrapper

### LOW Confidence (human review always)
- Refactor long methods
- Resolve circular dependencies
- Add error boundaries
- Write test implementations
- Major dependency upgrades

---

## Error Handling

| Scenario | Response |
|----------|----------|
| Zero packs selected | HALT with message: "registry selected zero packs". Do NOT silently proceed. |
| Worker crashes mid-audit | Results show `"in_progress"`. `--collect` reports incomplete workers. `--force` collects available. |
| Fix breaks the build (--fix) | Fix is reverted, recorded in results, worker continues. |
| Merge conflict (--fix) | HALT: (1) capture conflicted files to `.audit/current/merge-conflicts.md` FIRST, (2) run `git merge --abort`, (3) stop with message pointing to the report. |
| `.audit/current/` already exists | Coordinator asks: clean start, resume, or cancel. |
| Worktree already exists | Remove stale worktree first, then create fresh. |
| Task file missing | Worker errors with message to run `/audit` first. |
| Task agent times out | Collect proceeds with completed workers, reports incomplete ones. |
| All Task agents fail | Report failure, suggest `--manual` mode. |
| `--single` with `--fix` | Print note: `--single is read-only; --fix ignored`. Proceed read-only. |

---

## Spine Execution Ownership & Merge Contract

**ADV-002. This section is the authoritative spec for Epic 1.7b orchestration.**

### Spine Execution (coordinator responsibility)

The **COORDINATOR** runs the deterministic spine **once per audit run** — never per-worker, never inside a worktree:

```
scripts/spine/run.sh \
  --repo  <ABSOLUTE repo root> \
  --tools <comma-list scoped to the union of the selected packs' tools[]> \
  --output <ABSOLUTE>/.audit/current/spine/findings.jsonl
```

- The repo path must be **absolute**. The spine must run against the main checkout, not a worktree.
- `--tools` must be the union of every `tools[]` array from the packs selected for this run. Do not run spine tools that no pack will consume.
- The output file is written to `.audit/current/spine/` (under the **main** checkout's `.audit/`, not under any worktree).

### Per-worker spine slices

Workers run in separate git worktrees and **cannot see** a relative `.audit/` under the main checkout. Every path a worker receives must be **absolute**.

At task-file-writing time (Phase M3/M4) the coordinator:

1. Filters the spine output by the pack's check-id namespaces and `tools[]` to produce a per-pack slice.
2. Writes the slice to `<ABSOLUTE>/.audit/current/spine/<pack-dir>.jsonl`.
3. Embeds the **absolute** slice path in the worker's task file as `spine_slice_path`.

Workers read their slice from that absolute path. They never access `.audit/current/spine/findings.jsonl` directly.

### Worker duties

For each pack a worker handles:

1. **Triage hybrid candidates**: for every finding in the spine slice with `detection: "hybrid"`, decide `confirmed` or `dismissed` and record a `spine_triage` entry in the results file. A finding is only dropped if ALL workers that named its fingerprint voted `dismissed`; a single `confirmed` vote from any worker overrides any number of `dismissed` votes.
2. **Add LLM-only findings**: run the pack's LLM/hybrid checks; emit new findings with `source: "llm"`.
3. **Never invent severity**: workers must NOT set severity, confidence, or fix_confidence from intuition. Use `schemas/severity-rubric.json` only. The merge step enforces this mechanically, but workers should follow it proactively to avoid spurious `agentReportedSeverity` entries.

### Worker results-file contract

Each worker writes a single JSON file. The ABSOLUTE path to this file (`.audit/current/results/worker-<id>.json`) is embedded in the worker's task file at the same time as `spine_slice_path`, so workers always receive it as an absolute path and never need to derive it from cwd.

```json
{
  "findings": [
    {
      "check_id":      "<pack>/<check>",
      "rule_id":       "<rule>",   // optional -- defaults to check_id when absent
      "severity":      "critical|high|medium|low|info",
      "confidence":    "high|medium|low",
      "detection":     "tool|llm|hybrid",
      "source":        "llm",
      "message":       "<human-readable description>",
      "location":      {"path": "<repo-relative path>", "line": 1},
      "fingerprint":   "<optional — kept VERBATIM if present>",
      "fix_confidence":"high|medium|low",
      "properties":    {}
    }
  ],
  "spine_triage": [
    {
      "fingerprint": "<fingerprint of a spine hybrid candidate>",
      "verdict":     "confirmed|dismissed",
      "note":        "<optional explanation>"
    }
  ]
}
```

`findings` contains only the worker's **new** LLM-detected findings. Spine findings are not re-emitted here; they are carried through by the merge step.

### `--single` mode

In `--single` mode there is no coordinator/worker split. The single session:

1. Runs the spine inline (same invocation as above, before dispatching its read-only subagents).
2. Dispatches read-only subagents per pack (they receive the absolute spine slice path and produce results files).
3. Runs the merge itself after all subagents complete.

`--single` is always read-only. `--fix` is silently ignored when combined with `--single`.

### Merge invocation

After all workers complete, the coordinator runs:

```
scripts/merge-findings.py \
  --spine  <ABSOLUTE>/.audit/current/spine/findings.jsonl \
  --llm    <ABSOLUTE>/.audit/current/results/worker-0.json \
  --llm    <ABSOLUTE>/.audit/current/results/worker-1.json \
  ...
  --rubric <ABSOLUTE>/schemas/severity-rubric.json \
  --repo   <ABSOLUTE repo root> \
  --output <ABSOLUTE>/.audit/current/findings.jsonl
```

`--repo` must be the same absolute repo root passed to `scripts/spine/run.sh`. It ensures fingerprints computed for location paths are cwd-independent so baseline comparisons remain stable across invocations from different directories.

The merger:

- Deduplicates findings by fingerprint (tool source wins over llm source when fingerprints collide).
- Applies mechanical rubric overwrite: for every `check_id` in the rubric, overwrites `severity`, `confidence`, and `fix_confidence` with the rubric values. When the overwrite changes severity, preserves the original as `properties.agentReportedSeverity` (ADV-007 — calibration disagreements stay visible).
- Folds coverage-gap records from the spine through to the output (deduped).
- Validates every output finding against `finding.schema.json`.

---

## Severity Sourcing

**Agents MUST source severity, confidence, and fix_confidence from `schemas/severity-rubric.json`.** Do NOT invent or guess these values. For every finding whose `check_id` appears in the rubric, copy the rubric's `severity`, `confidence`, and `fix_confidence` verbatim. Preserve the agent-reported value in `properties.agentReportedSeverity` if it differs. For `check_id`s not yet in the rubric, set confidence to `"low"` and flag for rubric expansion.

---

## Notes

- **Always prompt the user** when `/audit` is called without flags - let them choose scope and execution strategy
- **Default mode is read-only** - no code changes, no branches, no PR
- **`--single` is always read-only** - `--fix` is silently ignored when combined with `--single`
- Auto-fix is opt-in (user selects "Analyze + auto-fix" or passes `--fix`)
- **Three execution strategies**: Parallel worktrees (recommended), single session, or multi-clone
- Multi-clone is opt-in and requires explicit verification that all clones are clean
- Worktrees are the safest isolation method - they never touch the user's working directory or sibling clones
- Pack selection is registry-driven: `scripts/detect-ecosystems.sh` + `scripts/registry.py` + `scripts/assign-packs.py`
- The spine runs once per audit run via `scripts/spine/run.sh`; findings are merged via `scripts/merge-findings.py`
- The output is always an audit report document + optional GitHub issues grouped by pack
- The `reference/multi-agent-config.md` file has full JSON schemas for coordination files
