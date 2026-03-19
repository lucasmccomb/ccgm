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

## Pages: Always Connect to Git for Auto-Deploy

**Always connect CF Pages projects to GitHub (or GitLab) for auto-deploy.** Manual or CI-based `wrangler pages deploy` is a fallback, not the default.

### When Creating a New CF Pages Project

1. **Preferred: Connect to GitHub** via the Cloudflare dashboard (Settings > Builds & Deployments > Git integration). This gives you:
   - Auto-deploy on push to production branch
   - Preview deployments on PRs
   - Deploy status checks on GitHub
2. **Fallback: CI-based deploy** if Git integration isn't possible (e.g., monorepo build complexity). Add `wrangler pages deploy` to CI with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets.
3. **Never rely on manual CLI deploys** as the only deploy mechanism.

### Red Flags for Missing Git Integration

- CF Pages dashboard shows "Git Provider: No" - project will NOT auto-deploy
- Last deployment timestamp is hours/days old despite recent merges
- Only one deployment ever exists (the initial manual deploy)

### How to Check

```bash
# In the dashboard: Pages project > Settings > Builds & Deployments
# Look for "Git Provider" - should show GitHub/GitLab, NOT "No"
```

### Fix Steps if Discovered Without Integration

1. **Immediate fix**: Deploy via CLI (`wrangler pages deploy`) to get current code live
2. **Permanent fix**: Either connect to GitHub in the CF dashboard, or add CI-based deploy step
3. **Tell the user** so they can connect Git integration in the dashboard (requires browser session)
