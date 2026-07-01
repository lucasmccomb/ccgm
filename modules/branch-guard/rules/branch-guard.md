# Branch Guard: No Work on the Default Branch

**Iron Law:** NO EDITS, NO STAGING, NO COMMITS WHILE HEAD IS ON THE DEFAULT BRANCH. BRANCH FIRST, THEN WORK.

This is not advisory. A deterministic PreToolUse hook (`branch-guard.py`) hard-blocks (exit 2, bypass-proof) any attempt to produce work on a repo's default branch (main/master, or whatever `origin/HEAD` names). The gate fires **before the first edit** — not at commit time — because uncommitted work on main is destroyed the next time main is synced to origin. That loss has actually happened; this hook exists so it cannot happen again.

## What Is Blocked on the Default Branch

| Operation | Tools |
|-----------|-------|
| File edits | Edit, MultiEdit, Write, NotebookEdit, filesystem-MCP write/edit/move |
| Staging and committing | Bash: `git add`, `git stage`, `git commit`, `git apply` (every `&&`/`;`/`\|` segment is scanned; `git -C <path>` is resolved and checked against the target repo) |

The file gate keys on the **target file's** repo, not the session cwd: editing a scratchpad, memory file, or any non-repo path is never blocked, and editing a file inside a main-checked-out repo is blocked even when the session cwd is elsewhere. Symlinks are resolved first, so editing an installed `~/.claude/...` symlink that points into a repo checked out on main is also caught.

## The Required Response to a Denial

When the guard blocks you, do exactly this — do not retry the blocked call, do not reach for the escape hatch:

```bash
git fetch origin && git checkout -b <type>/<short-desc> origin/<default-branch>
```

where `<type>` is one of `feature | fix | chore | docs` (e.g. `feature/add-login-form`, `fix/null-session-crash`). Then retry the original operation on the new branch.

## What Is Deliberately NOT Blocked

- **Any non-default branch**, including detached HEAD — work there freely.
- **In-progress rebase / merge / cherry-pick / revert / bisect** — conflict resolution requires editing files and running `git add` while the repo may report the default branch. The guard detects these states via `$GIT_DIR` markers and stands down.
- **Unborn HEAD** (fresh `git init` before the first commit) — a new repo's first commit legitimately lands on the default branch; bootstrap must work.
- **Repos with no `origin` remote** — the loss scenario this guard exists for is work destroyed when the default branch is hard-reset to origin. A local-only repo has nothing to sync from, so scratch `git init` repos and local journals stay frictionless. (An origin that exists but was never fetched is still guarded, via the local main/master fallback.)
- **Direct-to-main allowlisted repos** (`~/.claude/git-flow-direct-to-main-repos.json`, matched as substrings of the origin URL) — the same allowlist `enforce-git-workflow.py` honors, e.g. agent-log repos that commit tracking data straight to main.
- **Read-only git** (`status`, `log`, `diff`, `fetch`, `pull`, `checkout`, `switch`, branch creation) — the escape route must never be blocked.
- **`git push`** — already owned by `enforce-git-workflow.py`; the guard does not double-handle it.

## Escape Hatch

`ALLOW_MAIN_COMMIT=1` — as a session env var, or inline on a Bash command (`ALLOW_MAIN_COMMIT=1 git commit ...`). Use it ONLY for main-only operations the user explicitly requested (e.g. `appcast:` version bumps, release tagging). Reaching for the hatch because branching feels like friction is a violation of the workflow, not a workaround. The same variable already gates `enforce-git-workflow.py` and the force-push guard, so one hatch opens all three consistently — never leave it exported after the intentional operation completes.

## Relationship to the Other Layers

| Layer | Mechanism | When it fires |
|-------|-----------|---------------|
| `<workflow-reminder>` (enforce-issue-workflow.py) | Advisory context injection | On work-request prompts |
| **branch-guard.py (this rule)** | **Hard block, exit 2** | **Before the first edit / stage / apply on the default branch** |
| enforce-git-workflow.py | Hard block, exit 2 | `git commit` / `git push` on any protected branch (incl. dev/staging/etc.), commit-message format |

The advisory reminder stays — it teaches the workflow. This hook enforces it. `enforce-git-workflow.py` remains the wider net at commit/push time (it also covers non-default protected branches like `staging`); branch-guard is the earlier, narrower gate that keeps the default branch pristine.

## Known Gaps

- Raw shell writes (`echo > file`, `sed -i`, `tee`) are not detectable from the command string. The Edit/Write gate is the primary defense; write files through the file tools.
- `cd <other-repo> && git add .` is checked against the session cwd, not the `cd` target. Use `git -C <path>` (which IS resolved) when operating on another repo.
- The guard fails OPEN on git errors (cannot determine the branch → allow) so a broken git state never bricks the session.

## Red Flags

Stop if you catch yourself:

- Retrying a blocked Edit hoping the second attempt lands differently
- Prepending `ALLOW_MAIN_COMMIT=1` to get past the gate for ordinary feature work
- Doing "just one quick fix" on main because a branch feels heavyweight
- Writing files via shell redirection to route around the file-tool gate
- Exporting `ALLOW_MAIN_COMMIT=1` for a whole session
