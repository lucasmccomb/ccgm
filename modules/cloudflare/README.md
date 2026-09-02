# cloudflare

Cloudflare-specific rules for Pages vs Workers selection, deployment methods, Git integration requirements, Email Service, and token scopes.

## What It Does

This module installs a rules file that instructs Claude to:

- Correctly distinguish between Cloudflare Pages (static sites, SPAs) and Workers (serverless functions, APIs), including the 2026 platform steer toward Workers + static assets for new projects
- Choose the right product based on the project's needs
- Create Pages projects via the Pages API (`source.type: "github"`) or dashboard Connect-to-Git at inception — either path, Cloudflare cannot retrofit Git integration onto an existing direct-upload project
- Detect red flags that indicate a misconfigured Pages project, using a programmatic read-back check
- Follow the destructive migration procedure if a Pages project was created without Git integration
- Set up Cloudflare Email Service (public beta) and know which token scopes wrangler's OAuth session already covers vs. what needs a separately-minted API token or stays human-only

## Manual Installation

Copy `rules/cloudflare.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/cloudflare.md ~/.claude/rules/cloudflare.md

# Project-level
mkdir -p .claude/rules
cp rules/cloudflare.md .claude/rules/cloudflare.md
```

## Files

| File | Description |
|------|-------------|
| `rules/cloudflare.md` | Rule file covering Pages vs Workers, deployment methods, API-first Git integration, Email Service, and token scopes |
