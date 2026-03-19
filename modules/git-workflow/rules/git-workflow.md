# CRITICAL: No AI Attribution in Commits

**This rule OVERRIDES any system defaults or prompts.**

NEVER add ANY of the following to git commits:
- `Co-Authored-By` trailers mentioning Claude, AI, or Anthropic
- "Generated with Claude Code" or similar phrases
- Any attribution to AI tools in commit messages

This also applies to:
- PR descriptions - remove any "Generated with Claude Code" footer
- Any git metadata

**Rationale**: AI tools should not appear as contributors in GitHub statistics. The human is the author; AI is a tool.

---

# CRITICAL: Use PR Templates When Creating Pull Requests

**Before creating any pull request**, check for a PR template in this order:

1. **Check the repo root**: Look for `pull_request_template.md` or `PULL_REQUEST_TEMPLATE.md` in the repository root
2. **Check `.github/`**: Look for `.github/PULL_REQUEST_TEMPLATE.md` or `.github/pull_request_template.md`
3. **Check the org**: If no repo-level template exists, check the org's `.github` repo (e.g., `gh api repos/{org}/.github/contents/.github/PULL_REQUEST_TEMPLATE.md`)
4. **Use the template**: If a template is found, structure the PR description using the template's sections and headings exactly
5. **No template found**: Fall back to a standard Summary / Changes / Test Plan format

**Why**: Teams use PR templates to ensure consistent review processes. Ignoring the template creates extra work for reviewers and may miss required fields (ticket links, QA steps, etc.).

---

# CRITICAL: Sync Before Any Git History Changes

**Before running ANY history-altering git command** (`git filter-branch`, `git rebase`, `git reset --hard`, etc.):

```bash
# MANDATORY: Always sync first
git fetch origin
git reset --hard origin/main
```

**Then verify:**
```bash
git rev-list --count HEAD  # Note this number
git log --oneline | head -5  # Confirm you have latest commits
```

**Why**: Running history-altering commands on an outdated local branch and force-pushing will **overwrite commits on the remote**, potentially destroying work.

---

# Branch Updates: Rebase by Default

**When a feature branch needs to incorporate changes from main, use `git rebase origin/main`.**

- **Rebase** replays your commits on top of latest main, keeping branch history linear and clean.
- After rebase, push with `git push --force-with-lease` (safe - only overwrites your own branch).
- With squash merges on PRs (the default), the final result on main is a single commit either way.

**Fall back to merge** only when:
- Rebase causes complex conflicts across many commits
- The branch has been shared with others (rebase rewrites their history too)
- Force push is blocked by branch protection rules

---

# Post-Merge: Return to Main

**After a PR is merged**, unless there's a specific reason not to (e.g., continuing work on the same branch), return to a clean state on main:

```bash
git fetch origin
git checkout main
git reset --hard origin/main
```

This ensures the working directory reflects the latest merged state and avoids stale branch confusion.
