# Agent Manager TUI

> **Status: BETA (experimental)**
>
> This module is experimental and not recommended for daily use. It is excluded from default presets and must be explicitly selected during custom installation. A GUI-based replacement is being considered, so further development of this TUI may be paused.

A terminal UI for managing Claude Code agent processes across multi-clone repos. Built with Go and Bubble Tea.

## What It Does

The agent manager gives you a live view of all running Claude Code agents: their status, resource usage, log output, and session info. From a single pane you can launch new agents, stop or restart hanging ones, tail their logs, and export session data.

```
┌─ Agents ─────────────────────────────────────────┐ ┌─ Detail ──────────────────────┐
│ ● habitpro-ai-w0-c0   running  03:42  issue #204 │ │ Agent: habitpro-ai-w0-c0      │
│ ● habitpro-ai-w0-c1   running  01:15  issue #206 │ │ PID:   91234                  │
│ ○ habitpro-ai-w0-c2   stopped  --:--             │ │ Dir:   ~/code/habitpro-ai-... │
│ ⚠ habitpro-ai-w0-c3   hanging  08:01  issue #201 │ │ Issue: #204                   │
└──────────────────────────────────────────────────┘ └───────────────────────────────┘
┌─ Logs: habitpro-ai-w0-c0 ─────────────────────────────────────────────────────────┐
│ [14:32:01] Reading CLAUDE.md...                                                    │
│ [14:32:03] Checking open PRs...                                                    │
│ [14:32:05] Creating branch 204-habit-streaks from origin/main                      │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## Installation

### Via CCGM Installer (Recommended)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/lucasmccomb/ccgm/main/start.sh)
```

Select "Agent Manager TUI" from the module list. The installer runs `postInstall.sh` automatically, which downloads the correct binary for your platform.

### Manual Installation

1. Download the binary from [GitHub Releases](https://github.com/lucasmccomb/ccgm/releases/latest):

```bash
# macOS Apple Silicon
curl -fsSL https://github.com/lucasmccomb/ccgm/releases/latest/download/ccgm-agents_darwin_arm64.tar.gz | tar -xz
# macOS Intel
curl -fsSL https://github.com/lucasmccomb/ccgm/releases/latest/download/ccgm-agents_darwin_amd64.tar.gz | tar -xz
# Linux amd64
curl -fsSL https://github.com/lucasmccomb/ccgm/releases/latest/download/ccgm-agents_linux_amd64.tar.gz | tar -xz
```

2. Move the binary to `~/.ccgm/bin/`:

```bash
mkdir -p ~/.ccgm/bin
mv ccgm-agents ~/.ccgm/bin/
chmod +x ~/.ccgm/bin/ccgm-agents
```

3. Add `~/.ccgm/bin` to your PATH (if not already present):

```bash
echo 'export PATH="${HOME}/.ccgm/bin:${PATH}"' >> ~/.zshrc
source ~/.zshrc
```

4. Copy the slash command to your Claude commands directory:

```bash
cp modules/agent-manager/commands/agents.md ~/.claude/commands/agents.md
```

## Usage

Launch the TUI:

```bash
ccgm-agents
```

Or from within a Claude Code session:

```
/agents
```

## Keybindings

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `enter` | Select / open detail panel |
| `/` | Filter agents by name or status |
| `esc` | Back / close detail panel |
| `n` | Launch new agent in current repo |
| `s` | Stop agent (graceful SIGTERM) |
| `r` | Restart agent |
| `x` | Kill agent (force SIGKILL) |
| `tab` | Switch between panels |
| `e` | Export agent logs to file |
| `pgup` / `pgdn` | Scroll log viewer |
| `?` | Toggle help overlay |
| `q` / `ctrl+c` | Quit |

## Configuration

The agent manager reads `~/.ccgm/agent-manager/config.json`. If the file does not exist, defaults are used and the file is created on first run.

```json
{
  "data_dir": "~/.ccgm/agent-manager",
  "health_check_interval": "2s",
  "hanging_timeout": "60s",
  "log_max_size": 52428800,
  "log_retention_days": 7
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `data_dir` | `~/.ccgm/agent-manager` | Directory for agent state and logs |
| `health_check_interval` | `2s` | How often to poll agent status |
| `hanging_timeout` | `60s` | Time before an agent is marked as hanging |
| `log_max_size` | `52428800` (50 MB) | Maximum log file size before rotation |
| `log_retention_days` | `7` | Days to retain rotated logs |

## Agent Lifecycle

The agent manager tracks these states:

- **running** - Agent process is active and responding
- **stopped** - Agent exited cleanly (zero exit code)
- **hanging** - Agent has not produced output for longer than `hanging_timeout`
- **failed** - Agent exited with a non-zero exit code

From the TUI, use `s` to stop, `r` to restart, or `x` to force-kill any agent.

## Session Management

Agent sessions are persisted to `~/.ccgm/agent-manager/sessions/`. Each session records:

- Start and end time
- Working directory and clone identity
- Issue number (if claimed)
- Exit code and final status
- Log file path

Use `e` to export the current agent's log to a timestamped file.

## Building from Source

Requirements: Go 1.21+

```bash
cd modules/agent-manager/src
go build -o ccgm-agents ./cmd/ccgm-agents
# Or use make:
make build
# Cross-compile for all platforms:
make build-all
# Install to ~/.ccgm/bin/:
make install
```

## Dependencies

This module requires the **multi-agent** module (for multi-clone directory conventions). It is listed as a dependency and the installer enforces this.

## Platform Support

| Platform | Supported |
|----------|-----------|
| macOS (Apple Silicon) | Yes |
| macOS (Intel) | Yes |
| Linux amd64 | Yes |
| Linux arm64 | No |
| Windows | No |
