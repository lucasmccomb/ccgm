# launch

A `/launch <spec.md>` skill that takes a one-page spec and walks the agent end-to-end to a deployed Cloudflare Pages site. The skill is a markdown prompt the orchestrating agent reads and follows — ten phases from pre-flight to verification, with one unavoidable hand-off where the user performs the Cloudflare dashboard's Connect-to-Git step.

## The Karpathy Forcing Function

Karpathy on agent-native infra (Sequoia, 2026-04-29):

> "A lot of the work, a lot of the trouble was not even writing the code for Menu Gen. It was deploying it in Vercel because I had to work with all these different services... I had to go to their settings and the menus and configure my DNS... I would hope that I could give a prompt to an LLM, build menu gen, and then I didn't have to touch anything and it's deployed in that same way on the internet. I think that would be a good kind of a test for whether or not a lot of our infrastructure is becoming more and more agent native."

`/launch` is the test. Going from spec to deployed site requires multiple human-shaped steps today: dashboard project creation, DNS, secret provisioning. CCGM has `/cpm` for ongoing changes, `/ccgm-sync` for module sync, but no end-to-end `/launch`. This skill is also a probe — building it surfaces every place CCGM and Cloudflare infra are still human-shaped, and each gap is a follow-up.

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/launch/SKILL.md` | `~/.claude/skills/launch/SKILL.md` | The skill prompt — ten phases the agent follows |
| `examples/sample-spec.md` | `~/.claude/skills/launch/examples/sample-spec.md` | A small example spec the user can test against |

The skill is installed globally so `/launch` is available in every project context. The example spec is a copy-paste starting point, not installed anywhere automatically.

## Manual Installation

```bash
# From the CCGM repo root:
mkdir -p ~/.claude/skills/launch/examples
cp modules/launch/skills/launch/SKILL.md ~/.claude/skills/launch/SKILL.md
cp modules/launch/examples/sample-spec.md ~/.claude/skills/launch/examples/sample-spec.md
```

## Dependencies

- `cloudflare` — encodes the Connect-to-Git rule the skill must respect. The skill never runs `wrangler pages deploy <new-name>` for project creation; it stops at the Pages-creation step and asks the user to perform the dashboard flow. See the constraint section below.
- `git-workflow` — branch-from-origin/main, no AI attribution, PR template discipline.
- `docs-for-agents` — Phase 3 of the skill scaffolds an `AGENTS.md` next to the project README so the deployed project is itself agent-native.

## Usage

```bash
# Take a one-page spec and walk it to a deployed site:
/launch path/to/spec.md

# Dry-run: print every step that would be executed, do not run anything
/launch path/to/spec.md mode:dry-run
```

The skill expects a one-page spec in the format documented by `code-quality/rules/spec-is-the-artifact.md`: **Problem / Deliverables / Constraints / Done-when**. The skill is flexible to whatever the user provides — if a section is missing, it asks once and continues.

### Example flow

1. User writes `spec.md` (problem, deliverables, constraints, done-when).
2. User runs `/launch spec.md`.
3. Skill performs Phase 0 pre-flight (auth checks for `gh` and `wrangler`, spec parseability).
4. Skill parses the spec and confirms project name, framework default (Vite + React TS), required secrets.
5. Skill creates the GitHub repo, scaffolds the project, implements the spec, commits incrementally, pushes to `main`.
6. Skill stops at Phase 6 and tells the user: "Open the Cloudflare dashboard, Workers & Pages > Create > Pages > Connect to Git, point it at this repo, use these build settings, then say 'done' to continue."
7. User performs the Connect-to-Git step in the browser.
8. Skill resumes, provisions secrets via `wrangler pages secret put`, optionally attaches a custom domain, verifies the deployed URL, and reports.

## Constraints (Non-Negotiable)

### Connect-to-Git only — no direct-upload Pages projects, ever

The single most expensive Cloudflare mistake is creating a direct-upload Pages project (via `wrangler pages deploy <new-name>`) instead of a Git-connected one. Cloudflare does not support retrofitting Git integration onto an existing direct-upload project. The only fix is to delete and recreate, which means migrating custom domains, env vars, and bindings — multi-session production work.

**The `/launch` skill MUST NEVER run `wrangler pages deploy` to create a new project.** It stops at the Pages-creation step and instructs the user to perform the Connect-to-Git dashboard flow. This is enforced in the skill prompt's Phase 6, with explicit anti-pattern callouts. See `modules/cloudflare/rules/cloudflare.md` for the full rule.

### No AI attribution

Per `git-workflow.md`: no `Co-Authored-By` Claude/AI/Anthropic trailers, no "Generated with Claude Code" footers in commits or PR bodies. The human is the author; the agent is a tool.

### Spec is the input contract

The skill takes a spec. It does not generate a spec. If the spec is missing details the skill needs (project name, framework, secrets), the skill asks once and continues — it does not silently invent. See `modules/code-quality/rules/spec-is-the-artifact.md`.

## Scope

### v1 includes

- One-page spec parsing (loose format: problem/deliverables/constraints/done-when)
- GitHub repo creation via `gh repo create`
- Project scaffold (default: Vite + React TypeScript; spec can override)
- Implementation of spec deliverables
- Push to GitHub
- Pages project creation via Connect-to-Git (user performs the dashboard step)
- Secret provisioning via `wrangler pages secret put`
- Optional custom domain attachment
- Verification: `curl` against the assigned Pages URL, confirm 200 + expected content
- `mode:dry-run` that prints every command without executing
- A scaffolded `AGENTS.md` so the deployed project is itself agent-native (Phase 3)

### v1 explicitly does NOT include (deferred follow-ups)

- **Multi-cloud deploy targets.** CF Pages only. Workers, Vercel, Netlify, Render are follow-ups.
- **Multiple framework templates beyond default + override.** Vite + React TS is the default. The spec can override (e.g., `framework: next`, `framework: astro`, `framework: static`), but the skill does not ship pre-built scaffolds for every option in v1 — it shells out to the framework's own scaffolder (`npm create vite@latest`, `npx create-next-app@latest`, etc.).
- **Ongoing site updates.** The skill is for *initial launch*. Subsequent changes use `/cpm` for the commit/PR/merge cycle. Pages auto-deploys from the connected branch.
- **Domain registration.** The skill expects the user to already own the domain. It can attach an owned domain to the Pages project; it does not buy domains.
- **Building a full agent-native surface for the deployed project.** The deployed app is whatever the spec asks for. Producing a 12-tool agent-native surface as in `/agentic-eval` is a separate exercise.
- **Real end-to-end test against a fresh deployment.** Burning a real CF Pages project and a real GitHub repo for testing is out of scope for the PR that ships the skill. Real-world use will surface refinements and those are expected follow-ups.

## What `/launch` Is Not

- **Not a replacement for `/cpm`.** `/launch` is for the initial creation of a project. Once the project exists and Pages is auto-deploying, ongoing changes go through `/cpm` (commit, PR, merge).
- **Not a replacement for `/agentic-eval`.** `/launch` produces a deployed site. `/agentic-eval` evaluates whether that site (or any other system) satisfies the four agent-native principles. If you want a launched site that also passes agentic-eval, run both: `/launch` first, `/agentic-eval` against the result.
- **Not a planning tool.** If the spec needs to be designed first, use `/brainstorm` and `/xplan` to produce the spec, then feed it to `/launch`.

## Design Decisions

### Why a markdown skill prompt, not executable code

CCGM skills are markdown prompts the orchestrating agent reads and follows. They are not executable code. The orchestrator owns the tools (`Bash`, `Read`, `Write`, `gh`, `wrangler`); the skill encodes the procedure the orchestrator should follow. This matches the rest of the CCGM skill surface (`/ce-review`, `/research`, `/document-review`) and lets the skill compose with whatever tools the agent has at hand without re-implementing them.

### Why ten phases, not three

The natural seams of "launch a site from a spec" are: pre-flight, parse, repo creation, scaffold, implement, push, Pages, secrets, domain, verify, report. Collapsing them into three loses the failure-resume points — if the skill fails at "secrets," you do not want to re-run "scaffold." The phases correspond to resumable units of work.

### Why we stop for the Connect-to-Git step

The Cloudflare dashboard's Connect-to-Git flow requires the user's browser session and explicit OAuth authorization for the GitHub repo. There is no `wrangler` command that creates a Git-integrated Pages project. The Cloudflare API surface (per the `cloudflare` module's rule) does not expose this either. The skill stops, explains exactly what to do, and resumes when the user confirms. This is the one place `/launch` is human-shaped, and the gap is filed as part of the issue's "forcing function" framing.

## Karpathy citation

> "I would hope that I could give a prompt to an LLM, build menu gen, and then I didn't have to touch anything and it's deployed in that same way on the internet."
> — Andrej Karpathy, Sequoia interview, 2026-04-29

Source transcript: `~/code/docs/transcripts/karpathy-vibe-coding-to-agentic-engineering-2026-04-29.md`
