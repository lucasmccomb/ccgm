---
name: launch
description: >
  Take a one-page spec and reach a deployed Cloudflare Pages site without further human input — except for the unavoidable Cloudflare Connect-to-Git dashboard step, which the skill stops to ask for. Ten phases - pre-flight, parse spec, create GitHub repo, scaffold project, implement deliverables, push, Pages via Connect-to-Git, provision secrets, optional custom domain, verify and report. Default scaffold is Vite + React TypeScript; the spec can override. The skill NEVER runs `wrangler pages deploy <new-name>` to create a project — direct-upload Pages projects cannot be retrofitted with Git integration. Modes - interactive (default) and dry-run.
  Triggers: launch this spec, deploy this spec, ship this spec, take spec to deploy, one-prompt deploy, end-to-end launch, /launch.
disable-model-invocation: false
---

# /launch — One-Prompt Spec to Deployed Cloudflare Pages

A skill that walks a one-page spec all the way to a deployed Cloudflare Pages site. The skill is the prompt the orchestrating agent reads and follows; the orchestrator owns the tools (`Bash`, `Read`, `Write`, `gh`, `wrangler`). The skill is what makes the procedure repeatable.

This skill exists because, as Karpathy put it (Sequoia, 2026-04-29):

> "A lot of the work, a lot of the trouble was not even writing the code for Menu Gen. It was deploying it in Vercel because I had to work with all these different services. I had to go to their settings and the menus and configure my DNS. I would hope that I could give a prompt to an LLM, build menu gen, and then I didn't have to touch anything and it's deployed in that same way on the internet."

The skill is the test of whether CCGM + Cloudflare infra is agent-native enough yet. Every place the skill stops to ask the user is a gap that is filed as a follow-up.

---

## CRITICAL CONSTRAINT: Connect-to-Git only

**You must read this section before starting Phase 0.**

Cloudflare Pages projects MUST be created via the dashboard's `Workers & Pages > Create > Pages > Connect to Git` flow at inception. You CANNOT add Git integration to an existing direct-upload Pages project later — Cloudflare does not support that conversion.

Concretely, this skill MUST NOT run any of:

- `wrangler pages deploy <new-project-name>`
- `wrangler pages project create <new-project-name>` followed by `wrangler pages deploy`
- Any other CLI command that creates a NEW Pages project as a direct-upload one

If you do, the resulting project will never auto-deploy from `git push`. The user will discover this days or weeks later when the production site goes stale, and the only fix is to delete the project and recreate it via Connect-to-Git, migrating custom domains, env vars, and bindings — multi-session production work.

**This rule has no exceptions for v1 of `/launch`.** If `wrangler` is the only path and Connect-to-Git is unavailable, STOP and report `BLOCKED`. Do not "make progress" by direct-upload. See `~/.claude/rules/cloudflare.md`.

---

## Modes

Parse `$ARGUMENTS` for a mode token:

| Mode | Behavior |
|------|----------|
| `mode:interactive` (default) | Full pipeline. Skill asks targeted questions when the spec is silent. Executes commands. Stops at Phase 6 for the user to perform the Connect-to-Git step, then resumes. |
| `mode:dry-run` | Prints every `gh`, `git`, `npm`, `wrangler`, and `curl` command that would run, in order, with the inputs they would receive. Executes nothing. Skips the Phase 6 hand-off but prints the exact instructions the user would receive. Use this to verify the skill is correct against a spec before burning a real CF project. |

In `mode:dry-run` no files are written, no repos are created, no commits are made, no deployments occur. The output is a transcript the user can review.

---

## Inputs

```
/launch <path/to/spec.md> [mode:dry-run]
```

The spec is a one-page markdown file in the format documented by `code-quality/rules/spec-is-the-artifact.md`:

- **Problem** — what is broken or missing, why it matters
- **Deliverables** — what will exist when this is done
- **Constraints** — what must not change, what approaches are off the table
- **Done-when** — how completion is verified

The skill is flexible: not every section must be present. If a section is missing AND the skill needs that information to proceed (for example, the spec does not name a project), the skill asks once and continues. The skill never silently invents.

If the spec also includes any of these optional fields, the skill uses them:

- `project_name` — the GitHub repo name and CF Pages project name
- `framework` — overrides the default (Vite + React TS); valid values are `vite-react-ts` (default), `vite-react`, `vite-vanilla`, `next`, `astro`, `static`
- `domain` — a custom domain the user already owns
- `visibility` — `public` (default) or `private`; passed to `gh repo create`
- `secrets` — list of env-var names that must be set as Pages secrets
- `success_criteria` — a curl-able URL pattern + expected content fragment, used in Phase 9

If the spec is missing entirely or is unparseable, return `BLOCKED` with a one-line explanation.

---

## Phase 0: Pre-Flight

Run before any work. Each check is a one-line `Bash` invocation; the skill aborts and reports `BLOCKED` if any check fails.

### 0.1 Verify required CLIs exist and are authenticated

```bash
# gh
gh --version >/dev/null 2>&1 || { echo "BLOCKED: gh CLI not installed"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "BLOCKED: gh CLI not authenticated. Run: gh auth login"; exit 1; }

# wrangler
npx -y wrangler --version >/dev/null 2>&1 || { echo "BLOCKED: wrangler not available via npx"; exit 1; }
npx -y wrangler whoami >/dev/null 2>&1 || { echo "BLOCKED: wrangler not authenticated. Run: npx wrangler login"; exit 1; }

# git
git --version >/dev/null 2>&1 || { echo "BLOCKED: git not installed"; exit 1; }

# node + npm (for scaffold)
node --version >/dev/null 2>&1 || { echo "BLOCKED: node not installed"; exit 1; }
npm --version >/dev/null 2>&1 || { echo "BLOCKED: npm not installed"; exit 1; }
```

In `mode:dry-run`, print these commands as the verification plan but do not execute the auth checks (they have no side effects, but printing them as a plan is consistent with dry-run semantics).

### 0.2 Verify the spec exists and is parseable

```bash
test -f "<spec_path>" || { echo "BLOCKED: spec file not found at <spec_path>"; exit 1; }
wc -l "<spec_path>"  # sanity check: nontrivial content
```

If the spec file is empty or under 5 lines, return `NEEDS_CONTEXT` and ask the user to provide a real spec.

### 0.3 Print the plan

Before doing anything, print a summary of what the skill is about to do:

```
/launch — plan summary
- Spec: <spec_path>
- Project: <name from spec, or to be asked in Phase 1>
- Framework: <from spec, or default vite-react-ts>
- Domain: <from spec, or none>
- Mode: <interactive|dry-run>
- Phases: 0 (preflight, done) -> 1 (parse) -> 2 (repo) -> 3 (scaffold) -> 4 (implement) -> 5 (push) -> 6 (Pages: USER STEP) -> 7 (secrets) -> 8 (domain) -> 9 (verify) -> 10 (report)
```

In `interactive` mode, ask the user `proceed?` once. In `dry-run`, print the plan and proceed automatically (no side effects to confirm).

---

## Phase 1: Parse the Spec

Read the spec file. Extract the four canonical sections (Problem, Deliverables, Constraints, Done-when) and the optional fields listed in the Inputs section.

### 1.1 What to do if a required field is missing

If the spec does not include a usable project name (and there is no `project_name` field):

- Derive a candidate from the spec's Problem heading (kebab-case the title).
- Ask the user once via `AskUserQuestion`:

  > "I'm reading the spec but I do not see a project name. I propose `<derived-slug>`. Use it, or supply a different one?"
  > Options: `Use <derived-slug>`, `Custom (I'll type it)`, `Cancel`

If the spec does not specify a framework:

- Default is `vite-react-ts`. Tell the user (do not ask): "Defaulting to Vite + React TypeScript. Override in the spec with `framework: <value>` if you want something else."

If the spec does not list secrets:

- Assume zero secrets. Phase 7 becomes a no-op. The skill notes this in the final report.

### 1.2 Build the run config

Materialize a single in-memory config object the rest of the phases consume:

```
{
  "project_name": "<resolved>",
  "framework": "vite-react-ts",
  "domain": "<from spec or null>",
  "visibility": "public",
  "secrets": ["NAME1", "NAME2"],
  "success_criteria": {
    "url_pattern": "https://<project>.pages.dev",
    "expected_fragment": "<from spec, or null>"
  },
  "spec_path": "<spec_path>"
}
```

In `dry-run`, print this config and continue without further prompts.

---

## Phase 2: Create the GitHub Repo

```bash
# 2.1 Create the repo (--public or --private from spec)
gh repo create <owner>/<project_name> \
  --<public|private> \
  --description "$(grep -m1 '^# ' <spec_path> | sed 's/^# //')" \
  --confirm

# 2.2 Clone locally to a working directory under /tmp or the user's code dir
WORK_DIR="$HOME/code/<project_name>"
test -d "$WORK_DIR" && { echo "BLOCKED: $WORK_DIR already exists. Pick a different project name or remove the directory."; exit 1; }
gh repo clone <owner>/<project_name> "$WORK_DIR"
cd "$WORK_DIR"
```

Notes:

- `<owner>` is the authenticated GitHub user (`gh api user --jq .login`). The skill does NOT assume an org.
- If the repo already exists on GitHub, the skill MUST stop and ask: "A repo named `<owner>/<project_name>` already exists. Reuse it, or pick a different name?" Reuse is risky (may have stale main branch); default to picking a new name.
- The skill does NOT add the repo to any organization or grant access to any other user. Owner-only by default.

In `dry-run`, print the commands and a note that the working directory would be created at `<WORK_DIR>`.

---

## Phase 3: Scaffold the Project

Default: Vite + React + TypeScript.

```bash
# 3.1 Scaffold via Vite (using the chosen framework)
case "<framework>" in
  vite-react-ts) npm create vite@latest . -- --template react-ts ;;
  vite-react)    npm create vite@latest . -- --template react ;;
  vite-vanilla)  npm create vite@latest . -- --template vanilla-ts ;;
  next)          npx create-next-app@latest . --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --no-experimental-app ;;
  astro)         npm create astro@latest . -- --template minimal --typescript strict --install --no-git ;;
  static)        : ;;  # Phase 4 will write index.html directly
  *)             echo "BLOCKED: unknown framework <framework>"; exit 1 ;;
esac

# 3.2 Install deps. The Vite scaffolder may have already installed; running it
# again is idempotent and ensures the lockfile is up to date.
npm install

# 3.3 Add an AGENTS.md so the deployed project is itself agent-native (per docs-for-agents rule)
cat > AGENTS.md <<'EOF'
# AGENTS.md

Operational commands for this project. Human-readable docs are in README.md; this file is what an agent should run.

## Install

```bash
npm install
```

## Build

```bash
npm run build
```

## Dev

```bash
npm run dev
```

## Test

```bash
npm test  # if tests exist
```

## Deploy

This project deploys to Cloudflare Pages via Git integration. Push to `main` and Cloudflare auto-deploys.

```bash
git push origin main
```

To deploy a non-main branch as a preview, push the branch; Pages creates a preview deployment automatically.
EOF

# 3.4 Add a basic .gitignore augmentation if Vite did not include common entries
cat >> .gitignore <<'EOF'

# Cloudflare
.wrangler/
.dev.vars
EOF

# 3.5 First commit: scaffold
git add -A
git commit -m "Initial scaffold: <framework> via /launch"
```

Notes:

- The first commit message MUST NOT include any AI attribution. Per `git-workflow.md`, no `Co-Authored-By` Claude/AI/Anthropic, no "Generated with Claude Code" footer.
- The `AGENTS.md` is the agent-native counterpart to `README.md`. Per the `docs-for-agents` rule, any project that an agent will install/build/test/deploy/debug should have one. The skill writes it as part of scaffolding so the deployed project is born agent-native.
- For `static` projects, Phase 3 produces just the `AGENTS.md` and `.gitignore`; Phase 4 writes `index.html` and any other source files.

In `dry-run`, print the exact `npm create` invocation for the chosen framework, the `AGENTS.md` content, and the commit message; do not run anything.

---

## Phase 4: Implement the Spec

Read the spec's Deliverables section. Generate the code that satisfies them.

### 4.1 What "implement" means in this skill

The orchestrating agent owns implementation. The skill describes the procedure:

1. For each Deliverable line in the spec, decide which file(s) need to change.
2. Make the change. Use `Read` and `Edit` for existing files (the scaffold from Phase 3); use `Write` only for genuinely new files.
3. Commit incrementally. One commit per Deliverable, or one commit per logical chunk if Deliverables share files. The commit message names the deliverable: `Implement: <deliverable summary>`.
4. After all Deliverables are implemented, verify them against the spec's Done-when section. Run any commands the Done-when section calls out (tests, type-check, build).

### 4.2 Scope discipline

The skill implements ONLY what the spec asks for. If you find yourself wanting to add a feature, refactor adjacent code, or "improve" the scaffold beyond the deliverables — STOP. Note the observation in the final report under `Deferred suggestions` and proceed.

The spec is the contract. The PR for ongoing changes uses `/cpm`, not `/launch`.

### 4.3 Build verification

After all commits, run:

```bash
npm run build  # or framework-equivalent: vite build, next build, astro build
```

If the build fails, report `BLOCKED` with the build output. Do not push a project that does not build. Do not create the Pages project against a broken main.

In `dry-run`, print: "Implementation phase: would generate code for each deliverable in <spec>, commit incrementally, run `npm run build` to verify."

---

## Phase 5: Push to GitHub

```bash
git branch -M main
git push -u origin main
```

Do NOT push other branches in v1. The Pages Connect-to-Git flow defaults to `main` as production; preview branches are a follow-up concern.

In `dry-run`, print the command.

---

## Phase 6: Cloudflare Pages — USER STEP (Connect-to-Git)

**This is the only phase the skill cannot complete autonomously.** The skill stops here, prints clear instructions, and waits for the user to confirm.

### 6.1 What the skill prints

```
---
Phase 6: Cloudflare Pages project creation (Connect-to-Git)
---

This step requires your browser. The skill cannot do it for you. The
Cloudflare API does not expose a "create Pages project with Git
integration" endpoint, so the dashboard flow is the only correct path.

DO NOT run `wrangler pages deploy <project-name>` to "make progress".
That creates a direct-upload project that Cloudflare cannot retrofit
with Git integration. The only fix later is to delete and recreate.

Steps:

1. Open: https://dash.cloudflare.com/?to=/:account/workers-and-pages/create/pages
2. Click "Connect to Git"
3. Authorize the GitHub repo: <owner>/<project_name>
4. Select branch: main
5. Configure build settings:
   - Framework preset: <auto-detected for vite/next/astro, or "None" for static>
   - Build command:    <from table below>
   - Build output dir: <from table below>
   - Root directory:   /
6. Click "Save and Deploy"
7. Wait for the first deployment to finish (1-3 minutes)
8. Copy the assigned `.pages.dev` URL
9. Return here and paste the URL, or type "done" if there were no issues

Build settings by framework:

| Framework      | Build command   | Output directory |
|----------------|-----------------|------------------|
| vite-react-ts  | npm run build   | dist             |
| vite-react     | npm run build   | dist             |
| vite-vanilla   | npm run build   | dist             |
| next           | npm run build   | .next            |  (use the Next.js preset)
| astro          | npm run build   | dist             |
| static         | (leave empty)   | .                |

(Project name to use in the dashboard: <project_name>)

---
```

### 6.2 What the skill does after the user says "done"

Verify the project was created correctly:

```bash
# 6.3 Confirm the project exists with Git integration
npx -y wrangler pages project list 2>/dev/null | grep -E "<project_name>" || {
  echo "BLOCKED: project <project_name> not found in `wrangler pages project list`."
  echo "Did you complete the Connect-to-Git step in the dashboard?"
  exit 1
}

# 6.4 Capture the assigned Pages URL
# The user is asked to paste the URL when they confirm "done". Store it in PAGES_URL.
# If the user said "done" without a URL, default to the conventional pattern and ask once
# to confirm. The conventional pattern is https://<project_name>.pages.dev but Cloudflare
# may assign a hash-suffixed alias for projects that conflict.
PAGES_URL="https://<project_name>.pages.dev"  # default; override if user pasted a different one
```

If the user pasted the URL, use it. If they said "done" without a URL, ask once: "What's the assigned `.pages.dev` URL?" and store it.

The skill does NOT attempt to verify Git-Provider status programmatically in v1 — `wrangler pages project list` does not expose the field reliably. The skill trusts the user's confirmation that they used Connect-to-Git, and the user is on the hook for not having taken the direct-upload path. (The instructions printed in 6.1 are explicit; the rule lives in the skill.)

### 6.3 Dry-run behavior

In `dry-run`, print the full instruction block from 6.1 with the actual `<project_name>` substituted, and a note: "Skill would stop here in interactive mode. Skipping in dry-run; downstream phases assume the project exists at https://<project_name>.pages.dev."

---

## Phase 7: Provision Secrets

For each name in `secrets` from Phase 1's run config:

```bash
# 7.1 Ask the user for each secret value. Never log the value.
for SECRET_NAME in <secrets>; do
  read -rs -p "Value for $SECRET_NAME: " SECRET_VALUE
  echo "$SECRET_VALUE" | npx -y wrangler pages secret put "$SECRET_NAME" --project-name "<project_name>"
  unset SECRET_VALUE
done
```

Notes:

- The skill MUST NOT log secret values. Use `read -rs` (silent mode) and pipe to `wrangler` directly.
- If `<secrets>` is empty, this phase is a no-op. Print: "No secrets to provision."
- If a secret already exists, `wrangler pages secret put` overwrites it; that is acceptable behavior and the skill does not warn.
- After provisioning, trigger a redeploy by pushing an empty commit (Pages does not auto-redeploy on secret changes):

  ```bash
  git commit --allow-empty -m "Trigger redeploy: secrets provisioned"
  git push origin main
  ```

In `dry-run`, print the secret names and the `wrangler pages secret put` invocations without prompting for values.

---

## Phase 8: Custom Domain (Optional)

If the spec specifies a `domain`:

```bash
# 8.1 Attach the domain via wrangler
npx -y wrangler pages deployment tail --project-name "<project_name>" >/dev/null 2>&1 &  # smoke check the project is reachable
TAIL_PID=$!
sleep 1
kill $TAIL_PID 2>/dev/null

# 8.2 Add the custom domain
# Note: as of the skill's authoring, `wrangler pages domain add` exists; verify with `wrangler pages domain --help`
npx -y wrangler pages domain add "<domain>" --project-name "<project_name>" || {
  echo "Domain attach failed. Falling back to dashboard instructions:"
  echo "1. Open: https://dash.cloudflare.com/?to=/:account/workers-and-pages/<project_name>/custom-domains"
  echo "2. Click 'Set up a custom domain'"
  echo "3. Enter: <domain>"
  echo "4. Follow CNAME / DNS instructions"
  echo ""
  echo "This is a deferred step. The skill will continue to Phase 9 with the .pages.dev URL."
}
```

Notes:

- DNS propagation can take minutes. The skill does NOT block on DNS — it attaches the domain and continues. Phase 9 verification uses the `.pages.dev` URL, not the custom domain.
- If the user does not yet own the domain (DNS lookup fails), the skill prints: "Domain `<domain>` is not registered or does not have a DNS record yet. Skipping. Attach it later via the dashboard." Continues to Phase 9.

If no `domain` is in the spec, this phase is a no-op.

In `dry-run`, print the `wrangler pages domain add` invocation and the dashboard fallback URL.

---

## Phase 9: Verify the Deployment

```bash
# 9.1 HEAD request to the .pages.dev URL
PAGES_URL="https://<project_name>.pages.dev"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -I "$PAGES_URL")
test "$HTTP_STATUS" = "200" || {
  echo "BLOCKED: $PAGES_URL returned HTTP $HTTP_STATUS, expected 200."
  echo "Possible causes: deployment still in progress (wait 1-2 min and retry); build failed (check dashboard); project misconfigured."
  exit 1
}

# 9.2 Content check (if the spec provided expected_fragment)
if [ -n "<expected_fragment>" ]; then
  curl -s "$PAGES_URL" | grep -q "<expected_fragment>" || {
    echo "WARN: $PAGES_URL responded 200 but did not contain expected fragment: <expected_fragment>"
    echo "The site is live but may not match the spec's success criteria. Investigate."
  }
fi
```

Notes:

- Per the `condition-based-waiting` rule, do NOT add arbitrary `sleep` between Phase 6 and Phase 9. If the first `curl` returns a non-200 (likely a 522 or 503 while the build is in flight), poll with bounded retry: 5 attempts, 10 seconds apart, then BLOCKED.

```bash
for i in 1 2 3 4 5; do
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -I "$PAGES_URL")
  test "$HTTP_STATUS" = "200" && break
  sleep 10
done
test "$HTTP_STATUS" = "200" || { echo "BLOCKED: deployment did not return 200 within 50s"; exit 1; }
```

In `dry-run`, print the curl commands and the bounded-retry loop, do not execute.

---

## Phase 10: Report

Print a structured final report. Format:

```
---
/launch — DONE
---

Project:        <project_name>
Spec:           <spec_path>
Repo:           https://github.com/<owner>/<project_name>
Pages URL:      https://<project_name>.pages.dev
Custom domain:  <domain or "(none)">
Secrets set:    <comma-separated list, or "(none)">
Build status:   200 OK
Content check:  <"matched expected fragment" or "(skipped, no fragment in spec)">

Verification evidence:
- gh repo view <owner>/<project_name>: exists
- git log on main: <N> commits, last commit: "<last commit subject>"
- curl -I https://<project_name>.pages.dev: HTTP/2 200
- (if applicable) Custom domain status: attached / pending DNS / dashboard fallback

Deferred suggestions (NOT implemented; spec did not ask for these):
- <observation 1>
- <observation 2>
- (or "(none)")

Next steps:
- For ongoing changes: use /cpm to commit/PR/merge. Pages auto-deploys on push to main.
- To audit agent-native readiness: run /agentic-eval against the deployed surface.
- If the custom domain is still pending DNS, attach via the dashboard once DNS resolves.
```

End with a single-line status token on its own line:

```
DONE
```

Or `DONE_WITH_CONCERNS` if Phase 8 (custom domain) deferred to dashboard, or any non-blocking warning surfaced. The Concerns block lists each.

In `dry-run`, the final report is replaced with:

```
---
/launch — DRY RUN COMPLETE
---

The skill would have:
1. Verified gh, wrangler, git, node, npm
2. Parsed <spec_path> and built the run config (printed above)
3. Created GitHub repo <owner>/<project_name> as <visibility>
4. Cloned to <work_dir>
5. Scaffolded <framework>
6. Implemented <N> deliverables, committed each
7. Pushed to origin/main
8. Stopped to ask the user to perform the Connect-to-Git step
9. Provisioned <N> secrets via wrangler pages secret put
10. (if applicable) Attached <domain> via wrangler pages domain add
11. Verified https://<project_name>.pages.dev returns 200
12. Reported success

No commands were executed. No repos created. No deployments made.

DONE (dry-run)
```

---

## Failure Modes and Status Tokens

The skill ends with one of four status tokens, per CCGM convention:

| Token | When |
|-------|------|
| `DONE` | All phases completed; deployed URL returns 200; content check (if specified) matched; no deferred steps. |
| `DONE_WITH_CONCERNS` | Deployment is live but at least one phase deferred (e.g., custom domain pending DNS) or a non-blocking warning surfaced. The Concerns block names each. |
| `BLOCKED` | A phase failed in a way the skill cannot resolve (e.g., wrangler not authenticated, build failed, repo name conflict). The report names the phase and the specific failure. |
| `NEEDS_CONTEXT` | The spec is under-specified in a way that asking once cannot fix (e.g., the spec is empty, or Deliverables section is missing entirely). The report names the gap. |

Never end with a free-form summary. Always end with one of the four tokens on its own line.

---

## Anti-Patterns (Do NOT Do These)

- **Running `wrangler pages deploy <new-name>` to create a project.** Forbidden in v1. Direct-upload projects cannot be retrofitted with Git integration. STOP and report `BLOCKED` instead.
- **Skipping Phase 6 and assuming the user "knows" the dashboard step.** The skill's job is to make the procedure explicit. Print the instruction block in 6.1 verbatim, including the build command and output directory for the chosen framework.
- **Including AI attribution in commits or PR bodies.** No `Co-Authored-By` Claude/AI/Anthropic. No "Generated with Claude Code" footers. The human is the author.
- **Implementing more than the spec asks for.** If the spec says "build a landing page with three sections," do not also add an admin panel. Note adjacent suggestions in the Deferred suggestions block of the final report.
- **Logging secret values.** Use `read -rs` and pipe directly to `wrangler`. Never `echo` the value. Never include the value in a commit, branch name, or filename.
- **Sleeping on Phase 9 with arbitrary delays.** Use the bounded retry loop in 9.2. Per `condition-based-waiting`, fixed sleeps are an anti-pattern; bounded retries with a clear failure message are the correct shape.
- **Pushing a broken build.** Phase 4 ends with `npm run build`. If it fails, do not proceed to Phase 5. Pages will fail to build, the user will not have a deployed site, and they will have to debug from a partially-launched state.
- **Reusing an existing GitHub repo without explicit consent.** Phase 2's "repo already exists" branch defaults to picking a new name. Reuse only if the user explicitly says so.
- **Adding the agent as a contributor or collaborator on the new repo.** The repo is owned by the authenticated user; the agent is a tool, not a collaborator. Do not run `gh api repos/.../collaborators/...`.
- **Ending with prose instead of a status token.** End with exactly one of `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, `NEEDS_CONTEXT` on its own line.

---

## Rationalizations That Mean You Are About to Violate the Connect-to-Git Rule

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "Just one direct-upload to test the pipeline" | A direct-upload project becomes the production artifact. The user will not delete and recreate it later — they will live with a stale site. |
| "wrangler pages deploy is faster than asking the user to open the dashboard" | Faster now, multi-session migration later when the user discovers the site does not auto-deploy. |
| "The user said they're in a hurry, let me skip Phase 6" | Phase 6 cannot be skipped. The dashboard is the only correct path for project creation. Print the instruction block and wait. |
| "I'll create the project via wrangler now and convert to Git later" | Cloudflare does not support that conversion. There is no "later". |
| "I'll deploy via wrangler and ask the user to add Git integration after" | Same problem. Connect-to-Git is inception-only. |

If you find yourself reaching for `wrangler pages deploy <new-name>`, STOP. Read the constraint section at the top of this file again.

---

## Composition with Other CCGM Skills

- **`/cpm`** — for ongoing changes after the project is launched. `/launch` is initial-creation only.
- **`/agentic-eval`** — to evaluate whether the launched site satisfies the four agent-native principles. Run after `/launch` if the spec implies an agent-native surface.
- **`/brainstorm` and `/xplan`** — to produce the spec that `/launch` consumes. If the user has only a fuzzy idea, run those first.
- **`/research`** — for technical context the spec author might need before writing the spec.

`/launch` is one stop in the larger flow:

```
fuzzy idea -> /ideate -> /brainstorm -> /xplan -> spec.md -> /launch -> deployed site
                                                                   |
                                                                   +-> /cpm for ongoing changes
                                                                   +-> /agentic-eval for surface audit
```

---

## Source

Issue: ccgm#443.

Karpathy on agent-native infra (Sequoia, 2026-04-29):

> "I would hope that I could give a prompt to an LLM, build menu gen, and then I didn't have to touch anything and it's deployed in that same way on the internet. I think that would be a good kind of a test for whether or not a lot of our infrastructure is becoming more and more agent native."

Source transcript: `~/code/docs/transcripts/karpathy-vibe-coding-to-agentic-engineering-2026-04-29.md`.

The Cloudflare constraint that shapes Phase 6 lives in `~/.claude/rules/cloudflare.md`.
