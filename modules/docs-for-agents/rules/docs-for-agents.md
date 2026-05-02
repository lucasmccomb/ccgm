# Docs for Agents (AGENTS.md)

Every project that an agent will install, build, test, deploy, or debug needs an `AGENTS.md`. Human docs (README, CLAUDE.md) explain context and intent. `AGENTS.md` gives the agent exactly what it needs to act: one command per operation, nothing more.

Karpathy's pet peeve from the Sequoia vibe-coding interview: *"They still have docs that are fundamentally written for humans... why are people still telling me what to do? What is the thing I should copy-paste to my agent?"*

## How AGENTS.md Differs from README and CLAUDE.md

| File | Audience | Format | Purpose |
|------|----------|--------|---------|
| `README.md` | Human, first visit | Narrative prose | Explain what the project is and why it exists |
| `CLAUDE.md` | Claude Code, this repo | Mixed (prose + commands) | Repo conventions, gotchas, workflow rules |
| `AGENTS.md` | Any agent, any tool | Command blocks only | Copy-paste commands for every operation an agent must perform |

`AGENTS.md` has no narrative. It has labeled blocks. An agent reads the label, pastes the block, runs it.

## When to Ship an AGENTS.md

Ship `AGENTS.md` when any of the following are true:

- An agent will clone or install the project
- An agent will run a build, test, or lint step
- An agent will deploy the project
- An agent will debug a failure by reading logs or running diagnostics
- The project has non-obvious setup (env vars to set, migrations to run, secrets to provision)

Skip `AGENTS.md` if the project is a one-off script, a personal prototype, or has no expected agent consumers.

## What Goes in AGENTS.md

Exactly six labeled sections. Each section is one code block or a small sequence of code blocks. No prose between sections except one-line clarifications when the command alone is ambiguous.

### Section labels and what each contains

**Install:** All steps to get the project to a runnable state from a fresh clone. Package install, env file setup, migrations, secret provisioning. Every step, in order.

**Build:** The single command that produces the deployable artifact. If there are multiple targets (client + server, extension + background), list each command on its own labeled line inside the block.

**Test:** The command that runs the full test suite. If there is more than one suite (unit, integration, e2e), list each. Include the flag for watch mode if it exists, but label it separately.

**Deploy:** The command that ships to production. If deployment is multi-step (build, then push, then migrate), list each step in order. If the deploy requires a secret, name the env var; do not describe the dashboard.

**Debug:** One subsection per common failure mode. Label each `Debug <symptom>:`. Each block contains the command to inspect that symptom. Prefer log tails, status checks, and diagnostic queries over "open the dashboard."

## Format Conventions

- Use the file's section labels exactly as shown above. Agents pattern-match on them.
- Commands are absolute or explicitly relative to the repo root.
- Env var placeholders use `YOUR_VALUE_HERE` form, not angle brackets.
- No "click here", "navigate to", or "open the dashboard". If the operation requires a browser, say so explicitly (`# requires browser: go to Cloudflare Dashboard > Pages > Deployments`) and immediately follow with whatever CLI equivalent exists.
- Keep each block self-contained. An agent should be able to copy one block and run it without reading the others.
- If a command requires a prior command to have run, say so with a one-line comment (`# run Install first`).

## Anti-Patterns

| Pattern | Problem | Fix |
|---------|---------|-----|
| "Go to Settings > API Keys and copy your key" | Dashboard navigation; the agent cannot do this | `export API_KEY=YOUR_VALUE_HERE` — then tell the human where to get the value, in a comment |
| "Click the Deploy button" | UI action | Provide the CLI equivalent: `npx wrangler deploy` |
| "See README for setup" | Link to prose | Paste the relevant commands directly in Install |
| Long prose before each command | Agents skip prose to find the command | One-line comments only (`# installs dependencies`) |
| Partial commands (`npm install` without specifying the workspace) | Ambiguous; breaks in monorepos | `cd packages/api && npm install` |
| Vague debug: "Check the logs" | Agent does not know where logs are | `tail -n 50 /var/log/app/error.log` or `wrangler tail --env production` |
| Skipping env vars | Agent hits a missing-env error mid-operation | List every required env var in Install, even if the value must come from a human |

## Maintenance

Update `AGENTS.md` whenever:

- A new required env var is added
- A build command changes
- A new test suite is added
- The deploy procedure changes
- A new common failure mode is identified

`AGENTS.md` is a contract. A stale contract is worse than no contract because the agent runs a broken command with confidence.

## Template

See `modules/docs-for-agents/templates/AGENTS.md` for a skeleton with example commands based on a small static-site CLI project.
