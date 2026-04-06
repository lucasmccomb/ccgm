---
description: Launch the CCGM Agent Manager TUI for managing Claude Code agent processes
allowed-tools: Bash
---

# /agents - Agent Manager

Launch the CCGM Agent Manager TUI to monitor and control Claude Code agent processes across multi-clone repos.

## Usage

```
$ARGUMENTS
```

## Instructions

Run the agent manager binary:

```bash
~/.ccgm/bin/ccgm-agents
```

If the binary is not found at `~/.ccgm/bin/ccgm-agents`, inform the user that the agent-manager module may not be installed or the postInstall script may not have run. They can install it by re-running the CCGM installer or running `postInstall.sh` from `modules/agent-manager/` manually.

## Keybindings Reference

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `enter` | Select / open detail |
| `/` | Filter agents |
| `esc` | Back / close |
| `n` | Launch new agent |
| `s` | Stop agent |
| `r` | Restart agent |
| `x` | Kill agent (force) |
| `tab` | Switch panel |
| `e` | Export logs |
| `pgup` / `pgdn` | Scroll log viewer |
| `?` | Toggle help |
| `q` / `ctrl+c` | Quit |

## Configuration

The agent manager reads its configuration from `~/.ccgm/agent-manager/config.json`. If this file does not exist, sensible defaults are used:

- **Data directory**: `~/.ccgm/agent-manager/`
- **Health check interval**: 2 seconds
- **Hanging timeout**: 60 seconds
- **Log max size**: 50 MB
- **Log retention**: 7 days
