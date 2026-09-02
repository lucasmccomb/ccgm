# Cloudflare Rules

## Pages vs Workers: Choose the Right Product

Cloudflare Pages and Workers are **different products** for different use cases. Choosing the wrong one leads to confusing deployment errors.

### Comparison

| | Cloudflare Pages | Cloudflare Workers |
|---|---|---|
| **Use case** | Static sites, SPAs, JAMstack | Serverless functions, APIs |
| **Deploy method** | Git integration (auto-builds on push) | `npx wrangler deploy` |
| **Config** | Build command + output directory in dashboard | `wrangler.toml` |
| **Deploy command field** | Leave blank (Pages handles it) | Required |

### Before Setting Up Hosting

Determine the correct product:
1. Is this a static site / SPA? -> Use **Pages**
2. Does it need server-side logic at the edge? -> Use **Workers**
3. If unsure, check the Cloudflare docs first - don't guess

### How to Tell You're on the Wrong Product

- Need `wrangler deploy` or a deploy command -> You created a **Workers** project
- Errors like "Must specify a project name" or "Project not found" with wrangler -> **Workers**, not Pages
- For static sites, the deploy command field should be **empty** - Pages builds and deploys automatically

### 2026 platform steer: new SPAs toward Workers + static assets

Cloudflare's current docs recommend Workers with static assets, not Pages, for new single-page apps, and the Pages docs now carry a migration banner. This rule does not change which product it recommends by default in this change — the guidance above stays the default, and it stays fully correct for any existing Pages project. See the follow-up issue for evaluating a Workers-first default: `#1019`.

Workers Builds — the Git-connected build/deploy pipeline for Workers — has a documented API recipe: `PUT /accounts/{account_id}/builds/repos/connections` to connect the repo, then `POST /accounts/{account_id}/builds/triggers` to create the build trigger. Same one-time GitHub App precondition as Pages (see below).

Cloudflare's Code Mode MCP server (`mcp.cloudflare.com/mcp`) can reach both the Pages and Workers Builds endpoints in this rule through its generic `search()`/`execute()` tools. The dedicated Workers Builds MCP server is read-only — it lists and inspects builds, with no create/connect tools.

---

## Pages: MUST Be Created With Git Integration At Inception (CRITICAL)

**A Cloudflare Pages project MUST be created with GitHub integration at the moment of creation — either via the Pages API's `source` field or the dashboard's Connect-to-Git flow. You CANNOT add Git integration to an existing direct-upload Pages project later — Cloudflare does not support that conversion.** The only "fix" for a wrong-creation is to delete the project and recreate it with Git integration, which means migrating custom domains, environment variables, and bindings. This is multi-session work that affects production traffic.

This is the single most expensive Cloudflare mistake. Multiple agents have wasted multiple sessions on it. The root cause is always the same: an agent ran `wrangler pages deploy <new-project-name>` to "make progress" and unintentionally created a direct-upload project that can never auto-deploy.

**~99% of the time the intended outcome is a Pages project that auto-deploys from a GitHub repo.** Treat that as the default. The exceptions (deployable artifact lives outside Git, build complexity Cloudflare's environment cannot handle) are rare and should be confirmed with the user before going down the direct-upload path.

### Creating a New CF Pages Project (two correct paths)

**Path 1 — API (preferred).** `POST /accounts/{account_id}/pages/projects` accepts a `source` block that connects the project to GitHub at creation time. Confirmed live (2026-09-02) with a full end-to-end probe: the project was created with `source.type: "github"`, independently re-confirmed on a separate `GET`, kept (this is the real, permanent project — not a throwaway), and its first build deployed successfully (see "First deployment is not automatic" below).

```
POST /accounts/{account_id}/pages/projects
{
  "name": "<project_name>",
  "production_branch": "main",
  "source": {
    "type": "github",
    "config": {
      "owner": "<owner>",
      "repo_name": "<repo>",
      "deployments_enabled": true,
      "production_deployments_enabled": true,
      "pr_comments_enabled": true,
      "preview_deployment_setting": "all"
    }
  },
  "build_config": {
    "build_command": "<build command>",
    "destination_dir": "<build output dir>",
    "root_dir": ""
  }
}
```

`root_dir: ""` is the value the verified request actually used — not `"/"`. Neither research note documents `build_config` for the Pages API at all (the only `root_directory: "/"`-shaped text in the evidence is a different field name on the unrelated Workers Builds trigger endpoint); the live probe is the only real example, and it used an empty string.

`deployments_enabled` is Cloudflare's own schema marking it deprecated. Per the schema's own field description, `preview_deployment_setting` controls only whether commits to **preview** branches trigger a preview deployment — it says nothing about production, despite reading like a general "build every branch" switch. `production_deployments_enabled: true` is the field that actually governs production auto-deploy; the verified request sets both it and `preview_deployment_setting: "all"`, and keeps `deployments_enabled: true` alongside them as the still-accepted deprecated umbrella.

Auth: the verified request authenticated by reading the `oauth_token` field out of `~/.wrangler/config/default.toml` — the TOML file `wrangler login` already writes, which holds the token in plain text. Treat it as a secret: check its mode before reading, and never print it. Verified locally against wrangler 4.98.0 on 2026-09-02: that file's top-level keys are `oauth_token`, `expiration_time`, `refresh_token`, `scopes` (key names only — no value was ever read into any committed output). This is the same OAuth session Phase 0 of `/launch` already verifies with `wrangler whoami`; no separate token has to be minted just to create a Pages project (see "Token scopes and what stays human" below).

Read the token into a shell variable without echoing it, then send it via `curl -H "Authorization: Bearer $TOKEN"` (or a header file, `curl -H @tokenfile`) — never as a literal on a command line, since shell history and `set -x` both capture literals. Never use `curl -v`/`--verbose` or `set -x` around these calls. **Every report that attaches a request or response from this API must redact the `Authorization` header first** (e.g. `Authorization: Bearer [redacted]`), and never print or log the raw token value anywhere else. If the config file isn't present or readable in a given environment, or the `oauth_token` key is missing or empty, fall back to a `CLOUDFLARE_API_TOKEN` the user has set, or a connected Cloudflare MCP server — treat this as the normal fallback trigger, not an error to surface. If the user has to supply a token by hand, tell them to persist it (e.g. export it in their shell profile) so future runs don't ask again.

`{account_id}`: verified locally against wrangler 4.98.0 on 2026-09-02: `wrangler whoami`'s output table has two columns, "Account Name" and "Account ID". Resolve it in this order: (1) if `CLOUDFLARE_ACCOUNT_ID` is set, use it; (2) else if the table lists exactly one account (one data row), use that row's Account ID; (3) else — more than one account, or the table can't be parsed — ask the user which account to use and tell them to persist `CLOUDFLARE_ACCOUNT_ID` so future runs don't ask again.

**Precondition:** the "Cloudflare Workers and Pages" GitHub App must already be installed on the GitHub account (or org), with the target repo in its selected-repository list (or the App installed for "All repositories"). This is a one-time, per-account browser action — GitHub Apps cannot be installed by API. If the repo is not in the App's access list, the create fails; the evidence does not record the exact error body Cloudflare's Pages API returns for that specific case — the account behind the live probe already had the App installed, so its create succeeded on the first attempt and this failure path was never exercised (community reports describe an `8000007 Project not found`-style failure for a related "broken connection" case, not confirmed as the first-create error — treat that as unconfirmed, not the documented failure). **The one thing to stop and ask the user for is the GitHub App install** — everything else in this section is scriptable.

**First deployment is not automatic.** Creating the project does not start a build. The live probe's `POST /accounts/{account_id}/pages/projects` returned success but triggered nothing; a separate `POST /accounts/{account_id}/pages/projects/{name}/deployments` was required. If that trigger call itself fails (non-2xx), report `BLOCKED` with the status code and the redacted response body — do not start polling.

On success, that build then ran five stages (`queued`, `initialize`, `clone_repo`, `build`, `deploy`) end to end in about 76 seconds, confirmed by polling `GET /accounts/{account_id}/pages/projects/{name}/deployments/{deployment_id}` every 20 seconds until `stage: deploy, status: success`. The one live run behind this never failed — no failure stage occurred — so the evidence does not record the exact terminal-failure value of `status`; treat any `status` other than one indicating still-in-progress as terminal, stop polling immediately, and report it (redacted) rather than waiting out the full bound. Do not assume a prior `git push`, or the project-create call itself, produced a deployment — trigger it explicitly and poll for completion (sized well past 76s) before treating the project as live.

Safe pattern (verify before trusting the create; this is the pattern `/launch` Phase 6 implements):
1. Create with a throwaway name and `deployments_enabled: false`, `production_deployments_enabled: false` (or `preview_deployment_setting: "none"`).
2. `GET /accounts/{account_id}/pages/projects/{name}` and assert `result.source.type == "github"`.
3. `DELETE /accounts/{account_id}/pages/projects/{name}` the throwaway.
4. Create the real project with the production settings, then trigger and poll its first deployment per the paragraph above.

The live probe itself skipped this and created the real project name directly — it was a single supervised ops run with a human confirming each step. `/launch` runs unsupervised, so it follows the throwaway-first sequence instead: the real project name is only ever created once, successfully.

**Path 2 — Dashboard Connect-to-Git (fallback).** Use this when the GitHub App precondition is unmet and the user needs to install it anyway, or the API is unreachable:

1. Push the project to GitHub first (the repo must exist before you create the Pages project).
2. In the Cloudflare dashboard: **Workers & Pages > Create > Pages > Connect to Git**.
3. Authorize the GitHub repo and select the branch (typically `main`).
4. Configure build command + output directory.
5. Cloudflare provisions the project AND the GitHub integration in a single creation flow. Auto-deploy on push, preview deploys on PRs, and deploy status checks on GitHub all work from this point on.

Do NOT fall back to `wrangler pages deploy <new-name>` in either path to "get something live" — that creates a direct-upload project that Cloudflare cannot later convert.

### Acceptable exceptions to inception-time Git integration

The only legitimate reasons to create a direct-upload Pages project:
- The deployable artifact is genuinely not in a Git repo (rare; usually means reconsider the architecture).
- Build complexity that cannot run in Cloudflare's build environment AND cannot be solved by adding a CI step that runs `wrangler pages deploy` against a Git-connected project.

If neither applies — and they almost never do — the project goes through Path 1 or Path 2 above.

### How to Tell a Pages Project Was Created Wrong

Programmatic check (preferred): `GET /accounts/{account_id}/pages/projects/{name}` and read `result.source.type` — absent, or anything other than `"github"`, means direct-upload.

Dashboard symptoms:
- Cloudflare dashboard > Pages project > Settings > Builds & Deployments shows **"Git Provider: No"** — project will never auto-deploy
- Last deployment is days old despite recent merges to main
- Only one deployment ever exists (the initial CLI upload)
- The project page is missing the **Production / Preview** branch separator
- `wrangler pages project list` shows the project, but the dashboard shows no connected repo

### If You Inherit a Pages Project Without Git Integration

There is no in-place fix. Remediation is destructive:

1. **Confirm the gap with the user** — show `wrangler pages project list` output or a dashboard screenshot
2. **Inventory what must migrate**: custom domains, environment variables, KV/D1/R2 bindings, build settings, access policies
3. **Create a replacement project via Connect-to-Git** (steps above), using a temporary name if the production hostname is in use
4. **Move custom domains** from the old project to the new one once the new project is deploying cleanly
5. **Delete the old direct-upload project**

This affects production traffic. Do not start it without explicit user authorization.

**Stopgap until migration:** keep deploying via `wrangler pages deploy <existing-project-name>` so the site does not go stale. This buys time, not a fix.

---

## Email Service

Cloudflare Email Service (sending, not just inbound Email Routing) entered **public beta on 2026-04-16**. It supports arbitrary recipients, not just addresses you pre-verify — outbound sending requires the Workers Paid plan. Included quota is 3,000 sends/month per account, then $0.35 per 1,000; sends to already-verified destination addresses are free and don't count against quota.

Domain onboarding is API-doable, not dashboard-only:

1. `POST /zones/{zone_id}/email/sending/subdomains` — onboard the sending subdomain.
2. `GET /zones/{zone_id}/email/sending/subdomains/{subdomain_id}/dns` — returns the DKIM/SPF/DMARC/MX records Cloudflare generated; write them with the standard `POST /zones/{zone_id}/dns_records` call.

Runtime: bind `[[send_email]]` in `wrangler.toml`/`wrangler.jsonc` and call `env.EMAIL.send({to, from, subject, html, text})` from the Worker.

**Warning:** the third-party `cloudflare-email-service` skill (part of Cloudflare's own skills bundle, not a CCGM module) documents `wrangler email sending enable <domain>`, `wrangler email routing enable <domain>`, and `wrangler email sending dns get <domain>` CLI subcommands. **These commands do not exist** in the current `wrangler` CLI — confirmed against the live wrangler commands reference, which lists no `email` command group. Use the REST API endpoints above, or the `env.EMAIL` binding, instead.

## Token scopes and what stays human

wrangler's OAuth session (from `wrangler login`) carries `pages (write)`, `email_sending (write)`, and `email_routing (write)` — but only `zone (read)`. DNS record writes (attaching a custom domain, onboarding an email sending subdomain) need a separately-minted, scoped Cloudflare API token; minting that token is itself a one-time human action in the dashboard (`dash.cloudflare.com/profile/api-tokens`).

Confirmed human-only — no API, CLI, or Terraform path exists for any of these:

- **Cloudflare GitHub App install** — one-time per GitHub account/org, browser-only; GitHub Apps cannot be installed via API.
- **Scoped Cloudflare API token minting** — needed for anything wrangler's own OAuth scopes don't cover (DNS writes; the Workers Builds API also requires a user-scoped token, which account-scoped tokens cannot satisfy).
- **Google "Sign in with Google" OAuth client creation and redirect-URI edits** — Google Cloud Console UI only. No REST API, `gcloud` command, or Terraform resource creates or edits a Web-application OAuth client; the one narrow API that ever touched this space, `gcloud iap oauth-clients create`, was shut down 2026-03-19 and was locked to IAP usage even while it existed.
- **Anthropic API key minting** — the Admin API only lists and updates existing keys (rename, activate/deactivate); it cannot create one. Workspace spend caps are Console-only even though workspace creation itself is doable through the Admin API.
