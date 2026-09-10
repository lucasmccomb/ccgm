# Branch Guard: No Work on the Default Branch

No edits, staging, or commits while HEAD is on a repo's default branch (main/master, or whatever `origin/HEAD` names). Branch first, then work. A PreToolUse hook (`branch-guard.py`) hard-blocks (exit 2, bypass-proof) these operations, before the first edit rather than at commit time, because uncommitted work on main is destroyed the next time main is synced to origin.

## What Is Blocked on the Default Branch

| Operation | Tools |
|-----------|-------|
| File edits | Edit, MultiEdit, Write, NotebookEdit, filesystem-MCP write/edit/move |
| Staging and committing | Bash: `git add`, `git stage`, `git commit`, `git apply` (every `&&`/`;`/`\|` segment is scanned; `git -C <path>` is resolved and checked against the target repo) |

The file gate keys on the target file's repo, not the session cwd: editing a scratchpad, memory file, or non-repo path is never blocked, and editing a file inside a main-checked-out repo is blocked from any cwd. Symlinks are resolved first, so an installed `~/.claude/...` symlink into a repo on main is caught too.

## When the Guard Denies

Do not retry the blocked call and do not reach for the escape hatch. Branch, then retry:

```bash
git fetch origin && git checkout -b <type>/<short-desc> origin/<default-branch>
```

where `<type>` is `feature | fix | chore | docs`.

## What Is Not Blocked

- Any non-default branch, including detached HEAD.
- An in-progress rebase, merge, cherry-pick, revert, or bisect (detected via `$GIT_DIR` markers), since conflict resolution needs edits and `git add`.
- Unborn HEAD (a fresh `git init` before the first commit).
- Repos with no `origin` remote: nothing to sync from, so nothing to lose. An origin that exists but was never fetched is still guarded via the local main/master fallback.
- Direct-to-main allowlisted repos (`~/.claude/git-flow-direct-to-main-repos.json`, substring-matched against the origin URL), the same allowlist `enforce-git-workflow.py` honors.
- Gitignored target paths (file tools only), checked with `git check-ignore`, which never reports tracked files as ignored. This check fails closed: a git error means not-ignored and the block stands, because a broken git state must never widen the gate.
- Read-only git (`status`, `log`, `diff`, `fetch`, `pull`, `checkout`, `switch`, branch creation): the escape route is never blocked.
- `git push`, which `enforce-git-workflow.py` owns.

## Escape Hatch

`ALLOW_MAIN_COMMIT=1`, as a session env var or inline on one command, only for main-only operations the user explicitly requested (`appcast:` version bumps, release tagging). The same variable gates `enforce-git-workflow.py` and the force-push guard. Never leave it exported after the intentional operation.

## Relationship to the Other Layers

| Layer | Mechanism | When it fires |
|-------|-----------|---------------|
| `<workflow-reminder>` (enforce-issue-workflow.py) | Advisory context injection | On work-request prompts |
| branch-guard.py | Hard block, exit 2 | Before the first edit, stage, or apply on the default branch |
| enforce-git-workflow.py | Hard block, exit 2 | `git commit` and `git push` on any protected branch (including dev/staging), commit-message format |

## Known Gaps

- Raw shell writes (`echo > file`, `sed -i`, `tee`) are not detectable from the command string, so edits to tracked repo files go through Edit/Write/NotebookEdit, where this guard (and the freeze and advisor gates) can see them. Read-only work may use any tool.
- `cd <other-repo> && git add .` is checked against the session cwd, not the `cd` target; use `git -C <path>` for another repo.
- The guard fails open on git errors (cannot determine the branch, so allow) so a broken git state never bricks the session. The gitignored-path check is the one deliberate exception and fails closed.
