# model-vetting

Security vetting gate for integrating any new AI model — open-weights or hosted — into the Claude Code harness or the local development system.

## What It Does

This module installs a rule that blocks "just wire it up" model integrations behind a verification checklist:

- **Weights provenance** — the artifact must actually exist, come from the vendor's verified org, and be pinned to a revision hash. Announced ≠ released ≠ verified.
- **File-format safety** — safetensors/GGUF only; no pickle-based loads; no `trust_remote_code`.
- **License & data terms** — read the actual license; for hosted APIs, know retention, training-on-inputs, and jurisdiction before any private code flows there.
- **Serving path as supply chain** — aggregators, upstream providers, and translation proxies all see plaintext traffic; pin versions, scope keys to 0600 env files.
- **Staged agentic access** — a new backend model inherits every tool and credential the harness can reach. Access advances chat-only → sandboxed worktree → implementer-behind-two-stage-review → expanded roles, on evidence only.
- **Written verification record** — provenance, hashes, license, terms, and stage recorded next to the integration config; re-verified whenever the config changes.

## Manual Installation

Copy `skills/model-vetting/SKILL.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
mkdir -p ~/.claude/skills
cp -R skills/model-vetting ~/.claude/skills/model-vetting

# Project-level
mkdir -p .claude/rules
```

## Files

| File | Description |
|------|-------------|
| `skills/model-vetting/SKILL.md` | Rule file: the vetting checklist, staged-access table, rationalizations, and red flags |
