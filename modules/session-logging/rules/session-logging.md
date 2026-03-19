# Session Logging System (MANDATORY)

**Full documentation**: `~/.claude/log-system.md` - read it at session start if unfamiliar.

**Log repo**: Your agent log repo (typically at `~/code/{log-repo-name}/`)
**Log file**: `~/code/{log-repo-name}/{repo-name}/YYYYMMDD/agent-N.md`
**Agent identity**: Derived from working directory name suffix (`my-repo-1` -> agent-1, no suffix -> agent-0).

## Session Start

Pull latest logs, read today's log (or most recent), read other agents' logs, create today's log if needed. See `log-system.md` for session start requirements.

## Mandatory Log Triggers

Update the log **immediately** at each of these points - do NOT proceed until the log is written:

1. **After every git commit** - issue number, branch, what changed, decisions, gotchas
2. **After creating a PR** - issue number, PR URL, mark `#in-review`
3. **After PR merge** - mark `#completed`, commit/push log repo
4. **After closing an issue** - resolution, mark `#completed`, commit/push log repo
5. **Before context compaction** - current WIP, uncommitted changes, next step
6. **After PR merge - living docs check** - see "Living Documents" section below

## Log Repo Commits

```bash
cd ~/code/{log-repo-name} && git add -A && git commit -m "agent-N: {repo-name} update" && git pull --rebase && git push
```

Commit after: PR merge, issue close, session end, or every ~30 min of active work.

---

# Living Documents

Some projects maintain living documents (`README.md`, `docs/project-story.md`) that stay current with the codebase. After merging a PR, check whether living documents need updating.

## Post-PR-Merge Check

After every PR merge, before moving to the next task:

1. Check if the repo has a `README.md` and/or `docs/project-story.md`
2. If they exist, evaluate whether the merged PR warrants an update (see criteria below)
3. If yes, update the relevant file(s) in 5-10 minutes - not a rewrite, just targeted additions
4. Commit the updates as part of the current branch or as a fast-follow

## When to Update README.md

Update when the PR:
- Adds or removes a package
- Changes extension capabilities or permissions
- Changes dev commands, build system, or verification steps
- Changes external APIs, services, or required permissions
- Changes pricing, payment flow, or deployment configuration
- Adds significant new test coverage

**How**: Find the affected section. Add/modify the relevant table row, code block, or bullet. Keep it factual and terse.

## When to Update docs/project-story.md

Update when the PR:
- Represents a notable architectural decision or reversal
- Fixes a non-obvious bug with an interesting root cause
- Introduces or eliminates a pattern across the codebase
- Represents a methodology change (tooling, workflow, agent coordination)
- Is part of a new epic or phase
- Has an interesting human decision behind it

**How**: Find the section closest to the PR's topic. Add 2-5 sentences in narrative voice. If no section fits, add a new subsection. Check agent logs for decision color and human input.

## When NOT to Update

- Typo fixes, dependency bumps, or documentation-only changes
- Changes already well-described by the PR title
- The living document already covers the topic and the PR does not change the answer

## Scope Discipline

Living doc updates should take 5-10 minutes, not 30. If an update requires re-reading the entire codebase, add a new subsection and move on.

---

# Writing Style

## Avoid Em Dashes

Do not use em dashes in any output. Use alternatives instead:

| Instead of | Use |
|------------|-----|
| `word - word` (em dash) | `word - word` (hyphen), or restructure the sentence |
| Parenthetical aside with em dashes | Parentheses, commas, or a separate sentence |

This applies to all text output: conversation, commit messages, PR descriptions, code comments, documentation, and any other written content.
