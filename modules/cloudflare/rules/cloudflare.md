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

---

## Pages: MUST Be Created With Git Integration At Inception (CRITICAL)

**A Cloudflare Pages project MUST be created via the GitHub integration flow at the moment of creation. You CANNOT add Git integration to an existing direct-upload Pages project later — Cloudflare does not support that conversion.** The only "fix" for a wrong-creation is to delete the project and recreate it with Git integration, which means migrating custom domains, environment variables, and bindings. This is multi-session work that affects production traffic.

This is the single most expensive Cloudflare mistake. Multiple agents have wasted multiple sessions on it. The root cause is always the same: an agent ran `wrangler pages deploy <new-project-name>` to "make progress" and unintentionally created a direct-upload project that can never auto-deploy.

**~99% of the time the intended outcome is a Pages project that auto-deploys from a GitHub repo.** Treat that as the default. The exceptions (deployable artifact lives outside Git, build complexity Cloudflare's environment cannot handle) are rare and should be confirmed with the user before going down the direct-upload path.

### Creating a New CF Pages Project (the ONLY correct path)

1. Push the project to GitHub first (the repo must exist before you create the Pages project).
2. In the Cloudflare dashboard: **Workers & Pages > Create > Pages > Connect to Git**.
3. Authorize the GitHub repo and select the branch (typically `main`).
4. Configure build command + output directory.
5. Cloudflare provisions the project AND the GitHub integration in a single creation flow. Auto-deploy on push, preview deploys on PRs, and deploy status checks on GitHub all work from this point on.

The dashboard step requires the user's browser session. **If you are an agent and cannot complete it yourself, stop and ask the user to create the project this way.** Do NOT fall back to `wrangler pages deploy <new-name>` to "get something live" — that creates a direct-upload project that Cloudflare cannot later convert.

### Acceptable exceptions to inception-time Git integration

The only legitimate reasons to create a direct-upload Pages project:
- The deployable artifact is genuinely not in a Git repo (rare; usually means reconsider the architecture).
- Build complexity that cannot run in Cloudflare's build environment AND cannot be solved by adding a CI step that runs `wrangler pages deploy` against a Git-connected project.

If neither applies — and they almost never do — the project goes through the Connect-to-Git creation flow.

### How to Tell a Pages Project Was Created Wrong

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
