# Common Mistakes to Avoid

These are patterns where Claude has historically made errors. Pay special attention to avoid repeating them.

## 1. Shallow Directory Exploration in Monorepos

**Problem**: When exploring repositories, Claude tends to only check top-level directories and misses nested structures like `apps/`, `packages/`, or workspace subdirectories.

**Rule**: When performing operations across a monorepo (updating hooks, configs, dependencies, etc.), use a **two-method verification pattern**:

### Step 1: Initial Discovery (Glob)

Use Glob to find all relevant files recursively:
```bash
# Example: Find all package.json files
Glob: **/package.json

# Example: Find all .husky directories
Glob: **/.husky
```

### Step 2: Independent Verification

Run a second, independent discovery method to verify completeness:
```bash
# Verify package.json discovery
find . -name "package.json" -not -path "*/node_modules/*" | wc -l

# Verify .husky directories
find . -name ".husky" -type d | wc -l

# Verify workspace packages
cat package.json | jq '.workspaces // empty'
```

### Step 3: Compare and Reconcile

Before reporting completion:
1. Compare counts from both methods
2. If discrepancy exists, investigate missing items
3. Document which directories/files were processed

### Verification Checklist (REQUIRED before reporting "done")

For any multi-directory operation, confirm:
- [ ] Glob results match independent `find` count
- [ ] All workspace packages (from `package.json` or `pnpm-workspace.yaml`) were processed
- [ ] No subdirectories of `apps/`, `packages/`, `libs/` were skipped

### Common Scenarios

| Task | Glob Pattern | Verification Command |
|------|--------------|---------------------|
| Update pre-commit hooks | `**/.husky/*` | `find . -name ".husky" -type d` |
| Audit package.json files | `**/package.json` | `find . -name "package.json" -not -path "*/node_modules/*"` |
| Find TypeScript configs | `**/tsconfig*.json` | `find . -name "tsconfig*.json"` |
| Locate test files | `**/*.test.{ts,tsx}` | `find . -name "*.test.ts" -o -name "*.test.tsx"` |

**Never report "done" on a monorepo-wide task without completing the verification checklist.**

---

## 2. Branching Without Checking Open PRs (Dependency Blindness)

**Problem**: Creating a feature branch from `origin/main` without checking for open PRs. A foundational PR (build infrastructure, CSS pipeline) may still be unmerged. The new branch would be missing critical build config, breaking the project. Hours can be wasted debugging missing CSS, missing entry points, and broken UI - all because the branch was based on an incomplete `main`.

**Rule**: **Before creating any new branch**, check for open PRs and determine if the new work depends on any of them.

### Pre-Branch Checklist (MANDATORY)

```bash
# 1. List open PRs
gh pr list --state open

# 2. For each open PR, check if the new work touches the same packages/areas
# 3. If there's a dependency, either:
#    a. Merge the dependency PR first (if approved/ready)
#    b. Branch from the dependency PR's branch instead of main
#    c. Explicitly tell the user about the dependency and ask how to proceed
```

### How to Detect Dependencies

| New work touches... | Check for open PRs that... |
|---------------------|---------------------------|
| A package's source code | Add build config, entry points, or manifest entries for that package |
| UI components | Add CSS, styles, or theming infrastructure |
| A specific feature | Add the underlying API, types, or shared utilities for that feature |
| Extension behavior | Modify webpack config, manifest, or background scripts |

### Red Flags That You're on a Stale Base

- `dist/` is missing expected files after build
- CSS files aren't being generated or copied
- Entry points exist in source but not in build output
- Features that "were working before" suddenly break after switching branches

**Never assume `origin/main` has everything you need. Always verify open PRs first.**

---

## 3. ESLint React Fast Refresh Violations

**Problem**: Consolidating files and violating ESLint's React Fast Refresh rules, requiring a revert.

**Rule**: In React/TypeScript projects (especially Vite), NEVER export both React components and non-components (hooks, utilities, constants) from the same file. Fast Refresh requires:
- Components in their own files (only component exports)
- Hooks in separate files
- Utilities/constants in separate files

**Before consolidating or refactoring files**, check:
1. Is this a Vite project? (check for `vite.config.ts`)
2. Does ESLint config include `react-refresh` plugin?
3. Will the resulting file mix component and non-component exports?

---

## 4. Suggesting Already-Tried Solutions

**Problem**: When debugging, suggesting "run the full workflow" when the user had already done that before asking for help.

**Rule**: Before suggesting diagnostic steps, assume the user has already:
- Checked the obvious (restarted, refreshed, retried)
- Run the failing operation at least once
- Looked at basic error messages

**Instead of suggesting basic steps**, either:
- Ask "What have you tried so far?" if unclear
- Jump directly to deeper analysis (logs, data state, code paths)
- Focus on the specific error details they provided

---

## 5. Premature Solutions Without Full Context

**Problem**: Proposing fixes before fully understanding the codebase structure, leading to solutions that violate existing patterns or lint rules.

**Rule**: Before implementing fixes that touch multiple files or involve refactoring:
1. Check for ESLint/linter configurations (`.eslintrc`, `eslint.config.js`)
2. Look at existing patterns in similar files
3. Run linters BEFORE committing to catch violations early
4. If a lint rule seems wrong, ask the user rather than assuming it can be ignored

---

## 6. Git Multi-Clone Repos

Some repos use a multi-clone architecture for multi-agent parallel work. If your setup includes a multi-agent coordination guide, follow it for git workflow rules, issue claiming, and agent coordination.

Key reminders:
- **Prefer branching from `origin/main`** - `git checkout -b {branch} origin/main` ensures you start from latest
- **Check sibling clone branches** before claiming issues to avoid duplicate work

---

## 7. Cloudflare Pages vs Workers Confusion

**Problem**: Creating a Cloudflare Workers project instead of a Pages project for a static site, leading to multiple failed deploy attempts with confusing errors.

**Rule**: Cloudflare Pages and Workers are **different products** for different use cases:

| | Cloudflare Pages | Cloudflare Workers |
|---|---|---|
| **Use case** | Static sites, SPAs, JAMstack | Serverless functions, APIs |
| **Deploy method** | Git integration (auto-builds on push) | `npx wrangler deploy` |
| **Config** | Build command + output directory in dashboard | `wrangler.toml` |
| **Deploy command field** | Leave blank (Pages handles it) | Required |

**How to tell you're on the wrong product**:
- Need `wrangler deploy` or a deploy command -> You created a **Workers** project
- Errors like "Must specify a project name" or "Project not found" with wrangler -> **Workers**, not Pages
- For static sites, the deploy command field should be **empty** - Pages builds and deploys automatically

**Before setting up Cloudflare hosting**, determine:
1. Is this a static site / SPA? -> Use **Pages**
2. Does it need server-side logic at the edge? -> Use **Workers**
3. If unsure, check the Cloudflare docs first - don't guess

---

## 8. Cloudflare Pages Without Git Integration (No Auto-Deploy)

**Problem**: A CF Pages project was created without connecting it to GitHub. Pushes to main didn't trigger deploys, so the production site went stale after merges. The only way to deploy was manually via `wrangler pages deploy`.

**Rule**: **Always connect CF Pages projects to GitHub for auto-deploy.** Manual or CI-based `wrangler pages deploy` is a fallback, not the default.

### When Creating a New CF Pages Project

1. **Preferred: Connect to GitHub** via the Cloudflare dashboard (Settings > Builds & Deployments > Git integration). This gives you:
   - Auto-deploy on push to production branch
   - Preview deployments on PRs
   - Deploy status checks on GitHub
2. **Fallback: CI-based deploy** if Git integration isn't possible (e.g., monorepo build complexity). Add `wrangler pages deploy` to CI with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets.
3. **Never rely on manual CLI deploys** as the only deploy mechanism.

### How to Check if a Pages Project Has Git Integration

```bash
# Check the CF Pages project settings
# In the dashboard: Pages project > Settings > Builds & Deployments
# Look for "Git Provider" - should show GitHub/GitLab, NOT "No"
```

### Red Flags

- CF Pages dashboard shows "Git Provider: No" - project will NOT auto-deploy
- Last deployment timestamp is hours/days old despite recent merges
- Only one deployment ever exists (the initial manual deploy)

### If You Discover a Pages Project Without Git Integration

1. **Immediate fix**: Deploy via CLI (`wrangler pages deploy`) to get current code live
2. **Permanent fix**: Either connect to GitHub in the CF dashboard, or add CI-based deploy step
3. **Tell the user** so they can connect Git integration in the dashboard (requires browser session)
