# multi-agent

Multi-clone architecture for running parallel Claude Code agents on the same repository with issue claiming, port allocation, and coordinated workflows.

## What This Module Does

Enables multiple Claude Code agents to work on the same repository simultaneously using independent git clones. Each agent runs in its own clone directory with full git isolation - independent branches, independent PRs, no conflicts.

Key capabilities:

- **Parallel work**: Multiple agents work on different issues simultaneously
- **Issue claiming**: Agents claim issues via GitHub labels to avoid conflicts
- **Port allocation**: Dev server ports are offset per clone to prevent collisions
- **Coordination**: Cross-agent visibility via session logs
- **/mawf command**: Multi-Agent Workflow that takes unstructured feedback, splits it into issues, and spins up parallel agents

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/multi-agent.md` | rule | Parallel work preference and port allocation rules |
| `multi-agent-system.md` | doc | Full multi-agent coordination documentation |
| `commands/mawf.md` | command | Multi-Agent Workflow command (/mawf) |

## Dependencies

- **startup-dashboard**: Provides the `/startup` dashboard (tracking.csv claims, live sessions, recent activity) for cross-agent visibility

## Manual Installation

### 1. Copy Files

```bash
# Copy the rule file
mkdir -p ~/.claude/rules
cp rules/multi-agent.md ~/.claude/rules/multi-agent.md

# Copy the documentation
cp multi-agent-system.md ~/.claude/multi-agent-system.md

# Copy the mawf command
mkdir -p ~/.claude/commands
cp commands/mawf.md ~/.claude/commands/mawf.md
```

### 2. Set Up Multi-Clone Architecture

For each repository you want to run multiple agents on:

```bash
REPO="my-repo"
GITHUB_USER="your-username"
AGENT_COUNT=4

mkdir -p ~/code/${REPO}-repos
for i in $(seq 0 $((AGENT_COUNT - 1))); do
  CLONE_DIR="$HOME/code/${REPO}-repos/${REPO}-${i}"
  git clone git@github.com:${GITHUB_USER}/${REPO}.git "$CLONE_DIR"
  echo "CLONE_NUMBER=${i}" > "$CLONE_DIR/.env.clone"
done
```

### 3. Create Agent Labels

```bash
cd ~/code/${REPO}-repos/${REPO}-0
for i in $(seq 0 $((AGENT_COUNT - 1))); do
  gh label create "agent-${i}" --description "Being worked on by agent-${i}"
done
```

### 4. Add .env.clone to .gitignore

```bash
echo ".env.clone" >> ~/code/${REPO}-repos/${REPO}-0/.gitignore
```
