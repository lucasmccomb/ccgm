---
description: Run a task on __REMOTE_ALIAS__ by describing it in plain language
allowed-tools: Agent
---

# /onremote - Remote Server Task Runner

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: remote server task

Pass all workflow instructions and the input to the agent.

After the agent completes, relay its output to the user exactly as received.

---

## Workflow Instructions

Remote server: `__REMOTE_USER__@__REMOTE_HOST__` (__REMOTE_ALIAS__)

### Input

```
$ARGUMENTS
```

### If no arguments - Health Check

Run a health check and present a brief status report:

```bash
ssh __REMOTE_USER__@__REMOTE_HOST__ "uptime"
ssh __REMOTE_USER__@__REMOTE_HOST__ "df -h /"
ssh __REMOTE_USER__@__REMOTE_HOST__ "ps -u openclaw -o pid,command | grep -Ev '/System/|/usr/lib|/usr/sbin|Contents/MacOS|\.framework' | grep -v PID"
```

Present as:

```
Remote: __REMOTE_ALIAS__ (__REMOTE_HOST__)
Uptime:  {uptime}
Disk:    {df /}

Active processes:
{process list}
```

### If arguments provided - Execute Task

The arguments are a natural language description of what to do on the remote server.

1. Interpret the intent
2. Determine what shell commands are needed to accomplish it
3. Run them via SSH: `ssh __REMOTE_USER__@__REMOTE_HOST__ "..."`
4. Report back in plain language - what you did and what the result was

Examples of how to interpret input:
- "check if openclaw is running" → `ps aux | grep openclaw-gateway`
- "how much disk space is left" → `df -h /`
- "restart ollama" → `brew services restart ollama` (or find the right command)
- "show the last 50 lines of the openclaw log" → find the log file and tail it
- "what processes are using the most CPU" → `ps aux | sort -rk3 | head -10`

Use multiple SSH calls if needed. Interpret the task fully - do not ask clarifying questions unless the intent is genuinely ambiguous.
