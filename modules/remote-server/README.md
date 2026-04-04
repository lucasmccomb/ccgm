# remote-server

SSH access to a configured remote server. Adds a `/remote` command for health checks and remote command execution. All operations delegate to Haiku to minimize token usage.

## What It Installs

| File | Purpose |
|------|---------|
| `~/.claude/commands/remote.md` | `/remote` slash command |
| `~/.claude/rules/remote-server.md` | Tells Claude when/how to use the remote |
| `~/.claude/settings.json` | Adds `ssh`, `scp`, `rsync` to the allow list |

## Prerequisites

SSH key-based auth must be configured before using this module. Password prompts are not supported (Claude cannot enter them interactively).

```bash
# Copy your public key to the remote server (one-time setup)
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@remote-host
```

## Usage

```bash
/remote              # Health check: uptime, disk, active processes
/remote "command"    # Run a command on the remote server
```

Examples:

```bash
/remote "tail -n 50 ~/logs/app.log"
/remote "df -h"
/remote "ps aux | grep myapp"
/remote "brew services restart myservice"
```

## Manual Installation

If not using the CCGM installer, copy the files and substitute your values:

```bash
# In commands/remote.md and rules/remote-server.md, replace:
# __REMOTE_HOST__  → your server's IP or hostname
# __REMOTE_USER__  → your SSH username
# __REMOTE_ALIAS__ → a friendly name for the server
```

Then add to `~/.ssh/config` for convenience:

```
Host my-server
    HostName 192.168.1.100
    User myuser
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    ServerAliveCountMax 3
```
