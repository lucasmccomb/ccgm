---
description: Delegate work to cloud VMs - dispatch GitHub issues to autonomous Claude Code agents running on Hetzner Cloud
allowed-tools: Bash
---

# /dispatch - Delegate work to cloud VMs

Dispatch GitHub issues to autonomous Claude Code agents running on Hetzner Cloud VMs.

## Usage

The user will provide:
- Which repo to work on
- Which issues to dispatch (by number)
- Optionally: number of VMs, max turns, time limit

## Execution Steps

Follow these steps in order. Use the Bash tool to run the shell scripts.

### Step 1: Parse Arguments

Extract from the user's message:
- `REPO`: GitHub repo (owner/repo format, or just repo name to resolve from ~/code/)
- `ISSUES`: Comma-separated issue numbers
- `VM_COUNT`: Number of VMs (default: 3, or issues / 4 rounded up, whichever is smaller)
- `MAX_TURNS`: Max turns per agent (default: 200)
- `MAX_HOURS`: Max hours before auto-shutdown (default: 4)

### Step 2: Validate Prerequisites

```bash
# Check required tools
command -v hcloud >/dev/null 2>&1 || { echo "ERROR: hcloud CLI not installed. Run: brew install hcloud"; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI not installed. Run: brew install gh"; exit 1; }

# Check Hetzner auth
hcloud server-type list >/dev/null 2>&1 || { echo "ERROR: hcloud not authenticated. Set HCLOUD_TOKEN env var or run: hcloud context create"; exit 1; }

# Check GitHub auth
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh not authenticated. Run: gh auth login"; exit 1; }
```

### Step 3: Check VM Status

```bash
source modules/cloud-dispatch/lib/common.sh
bash modules/cloud-dispatch/lib/vm-status.sh
```

If no VMs are running, create them:
```bash
bash modules/cloud-dispatch/lib/vm-create.sh $VM_COUNT
```

If VMs exist, health-check them:
```bash
bash modules/cloud-dispatch/lib/vm-health.sh --all
```

### Step 4: Initialize Session Secrets

```bash
bash modules/cloud-dispatch/lib/secrets-init.sh
```

Ask the user for their GitHub token if not already configured:

"I need a GitHub fine-grained PAT with `contents:write` and `pull_requests:write` scoped to the target repo. Provide it now, or press Enter to use the token from `gh auth token`."

If the user provides a token, set `GITHUB_TOKEN` to that value. Otherwise:
```bash
GITHUB_TOKEN=$(gh auth token)
```

Then inject secrets to all VMs:
```bash
bash modules/cloud-dispatch/lib/secrets-inject-all.sh --github-token "$GITHUB_TOKEN"
```

### Step 5: Set Up Workspaces

```bash
bash modules/cloud-dispatch/lib/workspace-setup-all.sh "https://github.com/$REPO.git" --issues "$ISSUES"
```

### Step 6: Launch Agents

```bash
bash modules/cloud-dispatch/lib/agent-launch-all.sh --max-turns $MAX_TURNS --jitter 75
```

### Step 7: Report

Print a summary of what was dispatched:
- Number of agents launched
- Which issues were assigned to which VM/agent
- How to check status: "Run /dispatch-status to check progress"
- How to stop: "Run /dispatch-stop to terminate all agents"
- Estimated cost: roughly $0.015/hour per cx22 VM (3 VMs = $0.045/hour)
