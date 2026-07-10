# branch-guard

Hard enforcement that no agent ever works directly on a repo's default branch (main/master). A deterministic PreToolUse hook blocks the work **before the first edit** — not at commit time — so nothing can be produced on main and later destroyed by a `git reset --hard origin/main` sync.

## What This Module Does

Installs `branch-guard.py`, a PreToolUse hook wired (via settings.json merge) to Edit, MultiEdit, Write, NotebookEdit, the filesystem-MCP write tools, and Bash. While a repo's HEAD is on its default branch the hook hard-blocks (exit 2, survives bypass mode):

- **File edits** whose target file lives inside that repo — keyed on the file's own repo (symlinks resolved), not the session cwd, so scratchpads and non-repo files are never affected
- **Mutating git commands**: `git commit`, `git add`, `git stage`, `git apply` — every `&&`/`;`/`|` segment scanned, `git -C <path>` resolved against the repo it targets

The denial message teaches the fix: `git fetch origin && git checkout -b <type>/<short-desc> origin/<default>` with `<type>` ∈ feature/fix/chore/docs.

Default-branch detection: `origin/HEAD` → `origin/main`/`origin/master` → (only when an origin remote exists) local `main`/`master`. Fails open on any git error — the guard only denies on a positive determination.

### Exemptions (allowed even on the default branch)

| Exemption | Why |
|-----------|-----|
| `ALLOW_MAIN_COMMIT=1` (env or inline Bash prefix) | Intentional main-only ops (appcast version bumps, release tagging). Same hatch as `enforce-git-workflow.py`. |
| In-progress rebase / merge / cherry-pick / revert / bisect | Conflict resolution needs edits + `git add` mid-operation. Detected via `$GIT_DIR` markers. |
| Unborn HEAD (fresh `git init`) | A new repo's first commit legitimately lands on the default branch. |
| No `origin` remote | Nothing to sync from — the loss scenario cannot occur. Scratch repos and local journals stay frictionless. (Origin present but unfetched is still guarded via the local fallback.) |
| Repos in `~/.claude/git-flow-direct-to-main-repos.json` | Same allowlist the commit-time hook honors (e.g. agent-log repos). |
| Gitignored target paths (file tools only) | A gitignored file can never be committed to the default branch — outside the loss scenario (e.g. `.audit/` coordination state, `.env` files). Verified via `git check-ignore`; tracked files are never reported ignored, so tracked-but-pattern-matched paths stay blocked. Fails CLOSED on git errors (deliberate exception to the guard's fail-open convention — the exemption widens the gate, so a broken git state must never open it). |
| Detached HEAD, any non-default branch | Not the default branch. |

## Relationship to the `hooks` Module

Complements, does not replace:

- `enforce-issue-workflow.py` (UserPromptSubmit) stays as the **advisory** `<workflow-reminder>`.
- `enforce-git-workflow.py` (PreToolUse:Bash) stays as the **commit/push-time** gate and covers the wider protected-branch list (dev, staging, …) plus commit-message format.
- `branch-guard.py` closes the gap between them: the edits themselves.

The hook is dependency-free (no `hook_utils` import) so it works under both the symlink install and the plugin projection. Ships as its own module rather than growing `hooks` because installed modules do not re-link new files (#605).

## Files

| File | Type | Description |
|------|------|-------------|
| `hooks/branch-guard.py` | hook | The PreToolUse gate |
| `rules/branch-guard.md` | rule | The enforced contract, escape hatch, and red flags |
| `settings.partial.json` | config (merge) | PreToolUse wiring for file tools + Bash |

## Testing

```bash
bash modules/branch-guard/tests/test-branch-guard.sh
```

Covers: deny on main / allow on feature branch (Edit, Write-to-new-path, NotebookEdit, MCP write), master-default and origin/HEAD detection, `git add`/`commit`/`stage`/`apply` denial, `-C` targeting, compound commands, inline + env `ALLOW_MAIN_COMMIT=1`, merge/rebase/detached/unborn exemptions, the gitignored-path exemption (ignored new/existing paths allowed on main; tracked, untracked-not-ignored, and tracked-but-pattern-matched paths still blocked; ignored paths on feature branches unaffected), non-repo files, fail-open on malformed input.

## Manual Installation

```bash
# Hook
mkdir -p ~/.claude/hooks
cp hooks/branch-guard.py ~/.claude/hooks/branch-guard.py
chmod +x ~/.claude/hooks/branch-guard.py

# Rule
mkdir -p ~/.claude/rules
cp rules/branch-guard.md ~/.claude/rules/branch-guard.md

# settings.json — merge the PreToolUse entries from settings.partial.json
# into ~/.claude/settings.json (the installer does this automatically).
```
