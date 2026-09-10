# Common Mistakes to Avoid

Patterns where Claude has repeatedly gone wrong. Each is a problem and the rule that prevents it.

## 1. Branching Without Checking Open PRs

**Problem**: a feature branch cut from `origin/main` while a foundational PR (build infrastructure, CSS pipeline, entry points) is still unmerged is missing that config, and hours go to debugging missing CSS or broken UI on a stale base.

**Rule**: before creating any branch, run `gh pr list --state open` and check whether the new work touches the same packages or areas as an open PR. If it does, merge the dependency first, branch from its branch, or tell the user about the dependency and ask. Signs of a stale base: `dist/` missing expected files after build, CSS not generated, entry points present in source but absent from the build, features that "were working before" breaking after a branch switch.

## 2. ESLint React Fast Refresh Violations

**Rule**: in React/TypeScript projects, especially Vite, never export both React components and non-components (hooks, utilities, constants) from the same file. Fast Refresh needs components, hooks, and utilities in separate files. Before consolidating files, check for `vite.config.ts` and a `react-refresh` ESLint plugin.

## 3. Suggesting Already-Tried Solutions

**Rule**: assume the user has already restarted, refreshed, retried, run the failing operation, and read the basic error. Either ask what they have tried or go straight to deeper analysis (logs, data state, code paths) and the specific error they gave.

## 4. Premature Solutions Without Full Context

**Rule**: before a fix that touches multiple files or refactors, check the linter configuration (`.eslintrc`, `eslint.config.js`), look at existing patterns in similar files, and run the linter before committing. If a lint rule seems wrong, ask rather than ignore it.

## 5. Git Multi-Clone Repos

Two models exist: the workspace model (`~/code/{repo}-workspaces/{repo}-wX/{repo}-wX-cY/`, agent identity `agent-wX-cY`) and the flat clone model (`~/code/{repo}-repos/{repo}-N/`, agent `agent-N`). See `~/.claude/multi-agent-system.md`. Branch with `git checkout -b {branch} origin/main`, check sibling clones' branches before claiming an issue, and read `.env.clone` for agent identity, port offset, and workspace and clone numbers.

## 6. Cloudflare Pages vs Workers

Pages and Workers are different products: Pages for static sites and SPAs (Git-integration auto-deploy, blank deploy-command field), Workers for serverless functions and APIs (`wrangler deploy`, `wrangler.toml`). Reaching for `wrangler deploy` or hitting "Must specify a project name" on a static site means a Workers project was created by mistake. The `cloudflare` rule (`modules/cloudflare/rules/cloudflare.md`, loaded when a wrangler config is read) has the comparison and the checklist.

## 7. Cloudflare Pages Created Without Git Integration

**Problem**: `wrangler pages deploy <new-project-name>` creates a direct-upload Pages project that never auto-deploys from GitHub, and Cloudflare cannot retrofit Git integration; the only fix is deleting and recreating the project, migrating domains, env vars, and bindings.

**Rule**: create Pages projects with Git integration at inception, via `POST /accounts/{account_id}/pages/projects` with `source.type: "github"` or the dashboard's Connect-to-Git flow, never via `wrangler pages deploy <new-name>`. The one precondition is the Cloudflare GitHub App installed on the GitHub account; ask the user for that rather than falling back to direct upload. Verify with `GET /accounts/{account_id}/pages/projects/{name}` and confirm `source.type == "github"`. The `cloudflare` rule has the full procedure and the remediation steps.

## Adding New Mistakes

Add an entry when a pattern cost 30 or more minutes of wrong approach, is likely to recur across projects, and has a clear problem-and-rule shape. Run `/ccgm-sync` afterward so the entry survives module reinstall. Project-specific or one-off patterns belong in memory files instead.
