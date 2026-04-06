# cloud-dispatch

Delegate Claude Code agent work to Hetzner Cloud VMs. Boot ephemeral agents from a pre-baked golden image in 30-90 seconds, dispatch GitHub issues across them in parallel, and collect PRs when done.

## What This Module Does

- **Golden image**: Packer template that bakes a Hetzner snapshot with the full toolchain pre-installed
- **VM lifecycle**: Create, start, stop, and destroy VMs on demand
- **Secret injection**: Ephemeral GitHub and Anthropic credentials injected at session time via tmpfs
- **Workspace provisioning**: Clone repos and assign issues to agent slots across VMs
- **Agent dispatch**: Launch Claude Code agents via SSH with isolated user accounts
- **/dispatch command**: One-command interface to orchestrate the full pipeline

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| `hcloud` | `brew install hcloud` | Hetzner Cloud CLI |
| `terraform` | `brew install terraform` | (optional) Infrastructure as code |
| `packer` | `brew install packer` | Build golden images |
| `gh` | `brew install gh` | GitHub CLI |

You also need:
- A [Hetzner Cloud](https://console.hetzner.cloud) account with an API token
- An [Anthropic API key](https://console.anthropic.com) for agents
- A GitHub fine-grained PAT with `contents:write` and `pull_requests:write`

Set your Hetzner token:
```bash
export HCLOUD_TOKEN=your-token-here
# Or: hcloud context create my-project
```

## Quick Start

### 1. Build the Golden Image (one-time setup)

```bash
cd modules/cloud-dispatch/packer
packer init agent-image.pkr.hcl
HCLOUD_TOKEN=$HCLOUD_TOKEN packer build agent-image.pkr.hcl
```

Build takes 5-10 minutes. Creates a snapshot named `ccgm-agent-1.0.0` in your Hetzner project.

### 2. Dispatch Issues

In Claude Code, run:
```
/dispatch owner/repo --issues 42,43,44
```

This will:
1. Spin up 3 VMs (or reuse existing ones)
2. Inject your credentials securely
3. Clone the repo and assign one issue per agent
4. Launch 3-12 parallel Claude Code agents
5. Report back which agent got which issue

### 3. Monitor Progress

```
/dispatch-status
```

### 4. Collect and Clean Up

```
/dispatch-stop
```

## Commands

| Command | Description |
|---------|-------------|
| `/dispatch` | Dispatch GitHub issues to cloud agents |
| `/dispatch-status` | Check agent status and collect PR URLs |
| `/dispatch-stop` | Stop agents, optionally destroy VMs |
| `/vm-manage` | Low-level VM management (create/destroy/status/ssh) |

## Architecture

```
Orchestrator (local Claude Code)
  |
  +-- /dispatch owner/repo --issues 42,43,44
        |
        +-- vm-create.sh          # 3x cx22 VMs boot from golden snapshot
        +-- secrets-inject-all.sh # GitHub PAT + Anthropic key -> /run/secrets/agent-N/
        +-- workspace-setup-all.sh# git clone + issue assignment per agent slot
        +-- agent-launch-all.sh   # SSH -> tmux -> claude --dangerously-skip-permissions
              |
              +-- VM 1: agent-0 (issue 42), agent-1 (issue 43)
              +-- VM 2: agent-2 (issue 44), agent-3 (idle)
              +-- VM 3: idle
```

Each VM runs Ubuntu 22.04 LTS with 4 isolated agent user accounts (`agent-0` through `agent-3`). Agents run inside tmux sessions for persistence across SSH disconnects.

### VM Sizing

| VM Type | vCPU | RAM | Price/hr | Agents |
|---------|------|-----|----------|--------|
| cx22 | 2 | 4 GB | ~$0.005 | 2-4 |
| cx32 | 4 | 8 GB | ~$0.010 | 4 |
| cx42 | 8 | 16 GB | ~$0.020 | 4-8 |

Default: cx22. Override in `lib/common.sh`.

### Cost Reference

| Session | VMs | Duration | Estimated Cost |
|---------|-----|----------|----------------|
| Small (3 issues) | 1 VM | 2 hr | ~$0.01 |
| Medium (12 issues) | 3 VMs | 4 hr | ~$0.06 |
| Large (24 issues) | 6 VMs | 4 hr | ~$0.12 |

VMs are billed per hour. Destroy them when done to stop charges.

## Security Model

- **No secrets in git or cloud-init**: GitHub PAT and Anthropic key are injected at session time via SSH, written only to `tmpfs` at `/run/secrets/agent-N/`
- **Ephemeral SSH keys**: A session keypair is generated locally, pushed to VMs, and revoked by `secrets-cleanup.sh`
- **Agent isolation**: Each agent runs as a dedicated Linux user with no sudo access, `chmod 700` home dir, and `HISTFILE=/dev/null`
- **Network egress allowlist**: iptables rules allow only github.com (TCP 443+22), api.anthropic.com (TCP 443), and registry.npmjs.org (TCP 443)
- **Metadata API blocked**: The Hetzner metadata endpoint (169.254.169.254) is blocked for non-root processes
- **Fine-grained PAT**: Scope the GitHub token to the specific repo being worked on

## Lib Scripts

| Script | Description |
|--------|-------------|
| `lib/common.sh` | Shared config, SSH helpers, logging |
| `lib/vm-create.sh` | Boot N VMs from golden snapshot |
| `lib/vm-destroy.sh` | Destroy VMs (--all or by name) |
| `lib/vm-status.sh` | List VMs with state and IP |
| `lib/vm-health.sh` | SSH reachability + agent user checks |
| `lib/vm-ssh.sh` | Interactive SSH into a named VM |
| `lib/secrets-init.sh` | Generate session SSH keypair |
| `lib/secrets-inject.sh` | Inject credentials to one VM |
| `lib/secrets-inject-all.sh` | Inject credentials to all VMs |
| `lib/secrets-cleanup.sh` | Revoke session keys, clear tmpfs |
| `lib/secrets-rotate.sh` | Rotate credentials without destroying VMs |
| `lib/workspace-setup.sh` | Clone repo + assign issue on one VM |
| `lib/workspace-setup-all.sh` | Set up workspaces across all VMs |
| `lib/workspace-assign.sh` | Assign a specific issue to an agent slot |
| `lib/workspace-collect.sh` | Pull PR URLs and results from VMs |
| `lib/workspace-cleanup.sh` | Remove workspace dirs from VMs |

## Packer Golden Image

### What's Baked In

| Component | Version |
|-----------|---------|
| OS | Ubuntu 22.04 LTS |
| Node.js | 22 LTS (via NodeSource) |
| pnpm | latest stable |
| Claude Code CLI | pinned in `agent-image.pkr.hcl` |
| Playwright + Chromium | pinned |
| git, tmux, jq, curl | system packages |
| Python 3 | system package |

### Build with Custom Versions

```bash
HCLOUD_TOKEN=$HCLOUD_TOKEN packer build \
  -var "image_version=1.1.0" \
  -var "node_version=22" \
  -var "claude_code_version=1.5.0" \
  packer/agent-image.pkr.hcl
```

### Packer Files

| File | Description |
|------|-------------|
| `packer/agent-image.pkr.hcl` | Main Packer template |
| `packer/scripts/install-tools.sh` | Node.js, pnpm, Claude Code, Playwright |
| `packer/scripts/setup.sh` | Agent users, /opt/ccgm, SSH config |
| `packer/scripts/security-hardening.sh` | iptables, sshd, unattended-upgrades |
| `packer/scripts/validate.sh` | Post-build verification |

## Troubleshooting

**"hcloud not authenticated"**
Set `HCLOUD_TOKEN` in your environment or run `hcloud context create`.

**"No snapshot found matching ccgm-agent-*"**
Build the golden image first: `packer build packer/agent-image.pkr.hcl`.

**VM boots but health check fails**
SSH may not be ready yet. Wait 60 seconds and retry `/vm-manage health`. If it persists, check the VM console in the Hetzner dashboard.

**Agent exits immediately**
Check that secrets were injected: `bash lib/vm-ssh.sh VM_NAME "ls /run/secrets/agent-0/"`. If empty, rerun `secrets-inject-all.sh`.

**Rate limit errors across agents**
The `--jitter` flag in `agent-launch-all.sh` staggers agent starts. Increase the jitter value (default 75 seconds) if hitting API rate limits.
