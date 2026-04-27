# cloudflare

Cloudflare-specific rules for Pages vs Workers selection, deployment methods, and Git integration requirements.

## What It Does

This module installs a rules file that instructs Claude to:

- Correctly distinguish between Cloudflare Pages (static sites, SPAs) and Workers (serverless functions, APIs)
- Choose the right product based on the project's needs
- Create Pages projects via Connect-to-Git at inception (Cloudflare cannot retrofit Git integration onto an existing direct-upload project)
- Detect red flags that indicate a misconfigured Pages project
- Follow the destructive migration procedure if a Pages project was created without Git integration

## Manual Installation

Copy `rules/cloudflare.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/cloudflare.md ~/.claude/rules/cloudflare.md

# Project-level
cp rules/cloudflare.md .claude/rules/cloudflare.md
```

## Files

| File | Description |
|------|-------------|
| `rules/cloudflare.md` | Rule file covering Pages vs Workers, deployment methods, and Git integration |
