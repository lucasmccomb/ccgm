# cloud-dispatch

Hetzner Cloud VM orchestration for ephemeral Claude Code agent execution. Agents boot from a pre-baked golden image in 30-90 seconds rather than spending 5-8 minutes installing tools via cloud-init.

## What This Module Does

Provides the infrastructure layer for running Claude Code agents on disposable cloud VMs:

- **Golden image**: Packer template that bakes a Hetzner snapshot with the full toolchain pre-installed
- **VM lifecycle**: Create, start, stop, and destroy VMs on demand (future epics)
- **Agent dispatch**: SSH into a VM and invoke a Claude Code agent with injected credentials (future epics)

## Architecture

```
Orchestrator (local or CI)
  |
  +-- hcloud create-server --snapshot ccgm-agent-{version}
  |     (boots in 30-90s, all tools already installed)
  |
  +-- SSH as root -> inject agent credentials into /run/secrets/agent-N/
  |
  +-- SSH as agent-N -> run claude --dangerously-skip-permissions ...
```

## Packer Golden Image

The snapshot contains:

| Component | Version |
|-----------|---------|
| OS | Ubuntu 22.04 LTS |
| Node.js | 22 LTS (via NodeSource) |
| pnpm | latest stable |
| Claude Code CLI | pinned in `agent-image.pkr.hcl` |
| Playwright + Chromium | pinned |
| git, tmux, jq, curl | system packages |
| Python 3 | system package |

Security configuration baked into the image:

- Agent users `agent-0` through `agent-3` with `chmod 700` home dirs and no sudo
- `HISTFILE=/dev/null` for all agent users
- iptables egress allowlist: github.com (TCP 443+22), api.anthropic.com (TCP 443), registry.npmjs.org (TCP 443)
- 169.254.169.254 metadata API blocked for non-root users
- SSH password authentication disabled (key-only)
- Unattended security updates enabled

## Building the Image

### Prerequisites

- [Packer](https://developer.hashicorp.com/packer/install) >= 1.9.0
- `hcloud` Packer plugin (installed automatically by `packer init`)
- A Hetzner Cloud API token with read/write permissions

### Build

```bash
cd modules/cloud-dispatch/packer

# Initialize plugins
packer init agent-image.pkr.hcl

# Validate the template
packer validate agent-image.pkr.hcl

# Build the snapshot
HCLOUD_TOKEN=<your-token> packer build agent-image.pkr.hcl
```

The build takes 5-10 minutes. On success, a snapshot named `ccgm-agent-1.0.0` appears in your Hetzner Cloud project.

### Pinning Tool Versions

Override the defaults by setting variables:

```bash
HCLOUD_TOKEN=<token> packer build \
  -var "image_version=1.1.0" \
  -var "node_version=22" \
  -var "claude_code_version=1.5.0" \
  agent-image.pkr.hcl
```

## Files

| File | Description |
|------|-------------|
| `packer/agent-image.pkr.hcl` | Main Packer template |
| `packer/scripts/install-tools.sh` | Node.js, pnpm, Claude Code, Playwright |
| `packer/scripts/setup.sh` | Agent users, /opt/ccgm, SSH config |
| `packer/scripts/security-hardening.sh` | iptables, sshd, unattended-upgrades |
| `packer/scripts/validate.sh` | Post-build verification |

## Security Notes

- `HCLOUD_TOKEN` is consumed from the environment at build time and never written to disk
- The Hetzner metadata API (169.254.169.254) is blocked for all non-root processes
- Agent users have no sudo access and no persistent shell history
- Credentials (GitHub tokens, Anthropic keys) are injected at VM boot via tmpfs at `/run/secrets/agent-N/`, not baked into the image
