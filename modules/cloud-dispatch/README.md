# cloud-dispatch

Delegate Claude Code agent work to Hetzner Cloud VMs. Boot ephemeral agents from a pre-baked golden image in 30-90 seconds, dispatch GitHub issues across them in parallel, and collect PRs when done.

Up to 12 agents (3 VMs x 4 agents each) can run simultaneously, each working an independent GitHub issue from its own isolated user account.

## Overview

The dispatch pipeline runs entirely from your local machine via SSH:

1. **Create** cx22 VMs from a pre-baked Hetzner snapshot (30-90 seconds boot)
2. **Inject** credentials at session time via tmpfs (never in git or cloud-init)
3. **Provision** a git clone per agent slot with an issue assignment
4. **Launch** Claude Code via SSH into a named tmux session
5. **Monitor** via `/dispatch-status` or `agent-status.sh --all`
6. **Collect** PR URLs and commit hashes when work is done
7. **Destroy** VMs to stop billing

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| `hcloud` | `brew install hcloud` | Hetzner Cloud CLI |
| `terraform` | `brew install terraform` | Infrastructure provisioning (optional) |
| `packer` | `brew install packer` | Build golden images |
| `gh` | `brew install gh` | GitHub CLI |
| `jq` | `brew install jq` | JSON parsing |

You also need:

- A [Hetzner Cloud](https://console.hetzner.cloud) account with an API token
- An [Anthropic API key](https://console.anthropic.com) for agents, or an active Claude Max subscription
- A GitHub fine-grained PAT with `contents:write` and `pull_requests:write` scoped to the target repo
- `ssh-agent` running with `SSH_AUTH_SOCK` set

Set your Hetzner token:

```bash
export HCLOUD_TOKEN=your-token-here
# Or use named contexts:
hcloud context create my-project
```

## Quick Start

### 1. Build the Golden Image (one-time setup)

```bash
cd modules/cloud-dispatch/packer
packer init agent-image.pkr.hcl
HCLOUD_TOKEN=$HCLOUD_TOKEN packer build agent-image.pkr.hcl
```

Build takes 5-10 minutes. Creates a Hetzner snapshot labeled `purpose=ccgm-agent`.

### 2. (Optional) Apply Terraform Infrastructure

```bash
cd modules/cloud-dispatch/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your SSH public key and firewall settings
terraform init
terraform apply
```

This creates the named SSH key and firewall rules in Hetzner that the VM scripts expect.

### 3. Dispatch Issues

In Claude Code, run:

```
/dispatch owner/repo --issues 42,43,44
```

Or run the pipeline directly:

```bash
# Create VMs
bash lib/vm-create.sh 1

# Initialize session credentials
bash lib/secrets-init.sh

# Inject GitHub token into all agents
GITHUB_TOKEN=$(gh auth token)
bash lib/secrets-inject-all.sh --github-token "$GITHUB_TOKEN"

# Clone repo and assign issues
bash lib/workspace-setup-all.sh "https://github.com/owner/repo.git" --issues "42,43"

# Launch agents
bash lib/agent-launch-all.sh --max-turns 200
```

### 4. Monitor Progress

```
/dispatch-status
```

Or directly:

```bash
bash lib/agent-status.sh --all
```

### 5. Collect Results and Clean Up

```
/dispatch-stop
```

Or directly:

```bash
bash lib/workspace-collect.sh --all
bash lib/agent-stop.sh --all
bash lib/secrets-cleanup.sh
bash lib/vm-destroy.sh --all --force
```

## Commands

### /dispatch

Orchestrates the full pipeline: creates VMs if needed, injects credentials, provisions workspaces, and launches agents.

```
/dispatch owner/repo --issues 42,43,44
/dispatch owner/repo --issues 42,43,44 --vm-count 2 --max-turns 100
```

Arguments extracted from the message:

- `REPO` - GitHub repo in `owner/repo` format
- `ISSUES` - Comma-separated issue numbers
- `VM_COUNT` - Number of VMs to create (default: 3, or ceil(issues/4), whichever is smaller)
- `MAX_TURNS` - Max turns per agent (default: 200)

### /dispatch-status

Checks the status of all running agents and reports PR URLs, last log line, and elapsed time.

```
/dispatch-status
```

### /dispatch-stop

Stops all running agents and optionally destroys VMs.

```
/dispatch-stop
/dispatch-stop --destroy    # also destroys VMs after stopping
```

### /vm-manage

Low-level VM management. Accepts sub-commands:

| Sub-command | Description |
|-------------|-------------|
| `create [N]` | Create N VMs from golden image (default: 3) |
| `destroy [--all \| name]` | Destroy one or all VMs |
| `status` | List all VMs with state and IP |
| `health` | Run health checks on all VMs |
| `ssh <name>` | Open SSH session into a named VM |

## Architecture

### System Overview

```
MacBook (orchestrator)
  |
  +-- /dispatch owner/repo --issues 42,43,44
        |
        +-- vm-create.sh          # Boot cx22 VMs from golden snapshot
        +-- secrets-init.sh       # Generate session SSH keypair
        +-- secrets-inject-all.sh # GitHub PAT -> /run/secrets/agent-N/ on each VM
        +-- workspace-setup-all.sh# git clone + issue assignment per agent slot
        +-- agent-launch-all.sh   # SSH -> tmux -> claude --dangerously-skip-permissions
              |
              +-- VM 1 (fsn1): agent-0 (issue 42), agent-1 (issue 43)
              +-- VM 2 (nbg1): agent-2 (issue 44), agent-3 (idle)
              +-- VM 3 (hel1): idle
```

VMs are spread round-robin across three Hetzner datacenters (fsn1, nbg1, hel1) for availability.

### VM Layout

Each VM runs Ubuntu 22.04 LTS with 4 isolated agent user accounts:

```
/
+-- home/
|   +-- agent-0/         # agent user 0
|   |   +-- workspace/   # git clone lives here
|   |   +-- assignment.json  # issue metadata
|   |   +-- status       # AGENT_RUNNING / AGENT_STOPPED / AGENT_TIMEOUT
|   |   +-- run.log      # stdout from claude process
|   +-- agent-1/  ...
|   +-- agent-2/  ...
|   +-- agent-3/  ...
+-- opt/
|   +-- ccgm/
|       +-- auto-shutdown.sh  # cron: idle shutdown after 15m, forced after 8h
+-- run/
|   +-- secrets/         # tmpfs - credentials live here only at runtime
|       +-- agent-0/
|       |   +-- github_token
|       |   +-- claude_auth
|       +-- agent-1/ ...
+-- var/
    +-- lib/ccgm/        # auto-shutdown state (last-active, vm-start timestamps)
    +-- log/ccgm-shutdown.log
```

### Security Model

- **Credentials not in git or cloud-init**: GitHub PAT and Anthropic key are injected at session time via SSH, written only to `tmpfs` at `/run/secrets/agent-N/`
- **Ephemeral session keys**: `secrets-init.sh` generates a per-session ed25519 keypair, loads it into ssh-agent, and registers the public key with Hetzner. `secrets-cleanup.sh` revokes it.
- **Agent isolation**: Each agent runs as a dedicated Linux user with no sudo access, `chmod 700` home directory, and `HISTFILE=/dev/null`
- **Network egress allowlist**: iptables rules allow only `github.com` (TCP 443+22), `api.anthropic.com` (TCP 443), and `registry.npmjs.org` (TCP 443)
- **Hetzner metadata API blocked**: The metadata endpoint (169.254.169.254) is blocked for non-root processes
- **Fine-grained PAT scoping**: Scope the GitHub token to the specific repo being worked on

### Network

The Terraform config creates a Hetzner firewall (`ccgm-dispatch-firewall`) that:

- Allows inbound SSH (port 22) from any source
- Blocks all other inbound traffic

On each VM, iptables rules (set by the golden image security hardening script) control egress:

- Allowlisted outbound: `github.com`, `api.anthropic.com`, `registry.npmjs.org`
- Everything else blocked for non-root users

### VM Sizing

| VM Type | vCPU | RAM | Price/hr | Recommended agents |
|---------|------|-----|----------|--------------------|
| cx22 | 2 | 4 GB | ~$0.005 | 1-2 |
| cx32 | 4 | 8 GB | ~$0.010 | 4 |
| ccx63 | 48 | 192 GB | ~$0.80 | 4 (memory-rich) |

Default is `ccx63` (set in `lib/common.sh` as `CCGM_SERVER_TYPE`). Override with:

```bash
CCGM_SERVER_TYPE=cx22 bash lib/vm-create.sh 3
```

### Cost Reference

Cost depends on VM type, session length, and whether you're using a Claude API key or Max subscription. VM costs only (Claude API/Max subscription is separate):

| VM type | VMs | Hours/day | VM cost/month estimate |
|---------|-----|-----------|------------------------|
| cx22 | 3 | 8 | ~$4 |
| cx32 | 3 | 8 | ~$7 |
| ccx63 | 3 | 8 | ~$580 |

VMs are billed per second on Hetzner. Destroy them when done to stop charges. The auto-shutdown cron job on each VM shuts it down after 15 minutes of inactivity or 8 hours of wall-clock time (whichever comes first).

## Script Reference

### VM Lifecycle

| Script | Usage | Description |
|--------|-------|-------------|
| `lib/vm-create.sh` | `vm-create.sh [count] [--type TYPE]` | Boot N VMs from golden snapshot |
| `lib/vm-destroy.sh` | `vm-destroy.sh --all [--force]` | Destroy VMs; prompts unless `--force` |
| `lib/vm-status.sh` | `vm-status.sh` | List all ccgm-agent-* VMs with IP and state |
| `lib/vm-health.sh` | `vm-health.sh --all` | SSH reachability + agent user + disk + memory |
| `lib/vm-ssh.sh` | `vm-ssh.sh <name>` | Interactive SSH into a named VM |

### Secret Management

| Script | Usage | Description |
|--------|-------|-------------|
| `lib/secrets-init.sh` | `secrets-init.sh` | Generate session keypair, register with Hetzner |
| `lib/secrets-inject.sh` | `secrets-inject.sh <ip> <agent-index> --github-token TOKEN` | Inject credentials to one agent slot |
| `lib/secrets-inject-all.sh` | `secrets-inject-all.sh --github-token TOKEN` | Inject to all agents on all VMs |
| `lib/secrets-cleanup.sh` | `secrets-cleanup.sh` | Revoke session key from Hetzner, clear tmpfs |
| `lib/secrets-rotate.sh` | `secrets-rotate.sh --github-token TOKEN` | Rotate credentials without destroying VMs |

### Workspace Management

| Script | Usage | Description |
|--------|-------|-------------|
| `lib/workspace-setup.sh` | `workspace-setup.sh <ip> <agent-index> <repo-url>` | Clone repo on one agent slot |
| `lib/workspace-setup-all.sh` | `workspace-setup-all.sh <repo-url> --issues "42,43"` | Clone and assign across all VMs |
| `lib/workspace-assign.sh` | `workspace-assign.sh <ip> <agent-index> <issue-num> <title>` | Write assignment.json to one slot |
| `lib/workspace-collect.sh` | `workspace-collect.sh --all [--json]` | Pull PR URLs and git state from all agents |
| `lib/workspace-cleanup.sh` | `workspace-cleanup.sh --all` | Remove workspace dirs from VMs |

### Agent Management

| Script | Usage | Description |
|--------|-------|-------------|
| `lib/agent-launch.sh` | `agent-launch.sh <ip> <agent-index> [--max-turns N]` | Launch one agent via SSH + tmux |
| `lib/agent-launch-all.sh` | `agent-launch-all.sh [--max-turns N] [--jitter N] [--dry-run]` | Launch all assigned agents with jitter |
| `lib/agent-status.sh` | `agent-status.sh --all` | Report status, issue, last log, PR URL per agent |
| `lib/agent-stop.sh` | `agent-stop.sh --all` | Kill tmux sessions and write AGENT_STOPPED |
| `lib/agent-collect.sh` | `agent-collect.sh --all [--json]` | Collect agent results (status, PR, log tail) |

### VM Auto-Shutdown

| Script | Location | Description |
|--------|----------|-------------|
| `lib/auto-shutdown.sh` | Installed on VM at `/opt/ccgm/auto-shutdown.sh` | Cron-based shutdown: idle after 15m, forced after 8h |

Configure via environment variables on the VM (`/etc/ccgm/env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_HOURS` | `8` | Wall-clock hours before forced shutdown |
| `IDLE_MINUTES` | `15` | Minutes of no active tmux sessions before idle shutdown |

## Golden Image

### Building

```bash
cd modules/cloud-dispatch/packer
packer init agent-image.pkr.hcl
HCLOUD_TOKEN=$HCLOUD_TOKEN packer build agent-image.pkr.hcl
```

Build takes 5-10 minutes. Creates a Hetzner snapshot with label `purpose=ccgm-agent`. The `vm-create.sh` script selects the most recently created snapshot with this label.

### Building with Custom Versions

```bash
HCLOUD_TOKEN=$HCLOUD_TOKEN packer build \
  -var "image_version=1.1.0" \
  -var "node_version=22" \
  -var "claude_code_version=1.5.0" \
  packer/agent-image.pkr.hcl
```

### When to Rebuild

Rebuild the golden image when:

- A new major version of Claude Code is released
- Node.js LTS version changes
- Security patches are needed (or allow unattended-upgrades to handle them)
- Every 4-8 weeks as general maintenance

### What Is Baked In

| Component | Notes |
|-----------|-------|
| OS | Ubuntu 22.04 LTS |
| Node.js | 22 LTS (via NodeSource) |
| pnpm | Latest stable |
| Claude Code CLI | Pinned version in `agent-image.pkr.hcl` |
| Playwright + Chromium | Pinned version |
| git, tmux, jq, curl, python3 | System packages |
| Agent users | `agent-0` through `agent-3` created |
| `/opt/ccgm/auto-shutdown.sh` | Installed and registered in cron |
| iptables egress rules | Applied via security-hardening.sh |

### Packer Files

| File | Description |
|------|-------------|
| `packer/agent-image.pkr.hcl` | Main Packer template |
| `packer/scripts/install-tools.sh` | Node.js, pnpm, Claude Code, Playwright |
| `packer/scripts/setup.sh` | Agent users, `/opt/ccgm`, SSH config |
| `packer/scripts/security-hardening.sh` | iptables, sshd hardening, unattended-upgrades |
| `packer/scripts/validate.sh` | Post-build verification |

## Terraform Infrastructure

The Terraform config in `terraform/` creates Hetzner resources that the scripts depend on:

- **SSH key** (`ccgm-dispatch-key`) - a placeholder used when creating VMs. The actual session key is generated by `secrets-init.sh`.
- **Firewall** (`ccgm-dispatch-firewall`) - inbound SSH only, all other inbound blocked

These resources are optional if you create them manually in the Hetzner dashboard, but Terraform makes it reproducible.

```bash
cd modules/cloud-dispatch/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars
terraform init && terraform apply
```

## Jitter

The `--jitter` option in `agent-launch-all.sh` (default: 90 seconds) staggers agent starts to avoid simultaneous Claude API requests hitting the rate limiter. With 4 agents and a 90s max jitter, total launch time is up to 4.5 minutes.

Increase jitter if you see rate limit errors. Set to 0 to disable (not recommended with more than 2 agents).

## E2E Testing

A manual end-to-end test script is provided at `tests/e2e-dispatch.sh`. It validates the full pipeline against real Hetzner infrastructure.

```bash
# Preview without executing (no cost)
bash tests/e2e-dispatch.sh --dry-run

# Full run (~$2-3 cost, auto-cleans up)
bash tests/e2e-dispatch.sh

# Leave VMs running after test (for manual inspection)
bash tests/e2e-dispatch.sh --skip-cleanup
```

Prerequisites: `HCLOUD_TOKEN` set, golden image built, `gh` authenticated, `ssh-agent` running.

## Troubleshooting

### "hcloud not authenticated"

Set `HCLOUD_TOKEN` in your environment or run `hcloud context create`.

### "No snapshot found matching label purpose=ccgm-agent"

Build the golden image first:

```bash
cd packer && packer build agent-image.pkr.hcl
```

### VM boots but health check fails

SSH may not be ready yet. Wait 60 seconds and retry `/vm-manage health`. Check whether the VM console in the Hetzner dashboard shows a boot error.

### Agent exits immediately after launch

Check that secrets were injected:

```bash
bash lib/vm-ssh.sh VM_NAME "ls /run/secrets/agent-0/"
```

If the directory is empty, rerun `secrets-inject-all.sh`.

### "SSH_AUTH_SOCK is not set"

`secrets-init.sh` requires a running `ssh-agent`. Start one:

```bash
eval "$(ssh-agent -s)"
```

Then rerun `secrets-init.sh`.

### Rate limit errors across agents

Increase the `--jitter` value when launching:

```bash
bash lib/agent-launch-all.sh --jitter 120
```

The default is 90 seconds. At 120 seconds, 4 agents take up to 6 minutes to start.

### "No running ccgm-agent-* VMs found"

Run `vm-status.sh` to see VM states. VMs may have auto-shutdown. Create new ones with `vm-create.sh`.

### Secrets-cleanup fails to find session file

If `/tmp/ccgm-session.json` was removed (e.g., VM reboot), manually delete the session key from Hetzner:

```bash
hcloud ssh-key list
hcloud ssh-key delete ccgm-session-TIMESTAMP
```

## Manual Installation

If you are not using the CCGM installer, copy these files manually:

1. Copy `modules/cloud-dispatch/` to a location of your choice
2. Copy `modules/cloud-dispatch/commands/*.md` to `~/.claude/commands/`
3. Copy `modules/cloud-dispatch/rules/cloud-dispatch.md` to `~/.claude/rules/`
4. Ensure all scripts in `lib/` are executable: `chmod +x lib/*.sh`
5. Set `HCLOUD_TOKEN` in your environment
6. Build the golden image (see Quick Start)
