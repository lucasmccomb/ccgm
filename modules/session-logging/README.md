# session-logging

Structured agent session logging system that provides continuity between sessions, cross-agent visibility, and work tracking with git-backed history.

## What This Module Does

This module establishes a centralized logging system where Claude Code agents record their work in a dedicated git repository. It enables:

- **Session continuity**: Pick up exactly where the previous session left off
- **Cross-agent visibility**: See what other agents are working on in real time
- **Context preservation**: Capture details that do not fit in git commits or issues
- **Work tracking**: Record completed work, blockers, and decisions made
- **Remote backup**: All logs are git-tracked with a GitHub remote
- **Auto-startup**: Automatically run `/startup` on new sessions (works in VS Code, Cursor, and desktop app)

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/session-logging.md` | rule | Mandatory log triggers and living documents protocol |
| `log-system.md` | doc | Full logging system documentation |
| `commands/startup.md` | command | Session startup protocol (/startup) |
| `hooks/auto-startup.py` | hook | SessionStart hook that auto-runs /startup |
| `settings.partial.json` | config | Hook wiring for SessionStart event |

## Configuration

During installation, you will be prompted for:

- **Agent log repo name**: The name of the git repository for storing agent logs (e.g., `yourname-agent-logs`)
- **Create log repo now**: Whether to create the log repo immediately via `gh` CLI
- **Auto-run /startup**: Whether to automatically run `/startup` on new sessions (default: yes). This works across all Claude Code clients including VS Code, Cursor, and the desktop app. Can be toggled later via `CCGM_AUTO_STARTUP` in `~/.claude/.ccgm.env`.

## Dependencies

None.

## Manual Installation

### 1. Create the Log Repository

```bash
# Create a private GitHub repo for agent logs
gh repo create {your-username}/{log-repo-name} --private --clone
cd ~/code/{log-repo-name}
echo "# Agent Logs" > README.md
git add -A && git commit -m "Initial commit" && git push
```

### 2. Copy Files

```bash
# Copy the rule file
mkdir -p ~/.claude/rules
cp rules/session-logging.md ~/.claude/rules/session-logging.md

# Copy the documentation
cp log-system.md ~/.claude/log-system.md

# Copy the startup command
mkdir -p ~/.claude/commands
cp commands/startup.md ~/.claude/commands/startup.md

# Copy the auto-startup hook
mkdir -p ~/.claude/hooks
cp hooks/auto-startup.py ~/.claude/hooks/auto-startup.py
```

### 3. Configure the Hook

Add the SessionStart hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $HOME/.claude/hooks/auto-startup.py",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

### 4. Enable/Disable Auto-Startup

Add or update in `~/.claude/.ccgm.env`:

```bash
CCGM_AUTO_STARTUP=true   # or false to disable
```

### 5. Configure Paths

After copying, update the log repo path references in the rule file and log-system.md to point to your actual log repository location (e.g., `~/code/your-agent-logs/`).

### 6. Add to CLAUDE.md (Optional)

Add a reference to the session logging rule in your global CLAUDE.md:

```markdown
# Session Logging

See `~/.claude/rules/session-logging.md` and `~/.claude/log-system.md` for the full protocol.
```
