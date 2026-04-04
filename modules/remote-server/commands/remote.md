---
description: Run commands on __REMOTE_ALIAS__ and check its status
allowed-tools: Agent
---

# /remote - Remote Server Operations

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: remote server operations

Pass all workflow instructions and the input arguments to the agent.

After the agent completes, relay its output to the user exactly as received.

---

## Workflow Instructions

Remote server: `__REMOTE_USER__@__REMOTE_HOST__` (__REMOTE_ALIAS__)

### Input

```
$ARGUMENTS
```

### Health Check (no arguments)

Run a health check on the remote server and present a concise status report.

```bash
ssh __REMOTE_USER__@__REMOTE_HOST__ "uptime"
ssh __REMOTE_USER__@__REMOTE_HOST__ "df -h /"
ssh __REMOTE_USER__@__REMOTE_HOST__ "ps aux | grep -Ev 'grep|/System/|/usr/lib|/usr/sbin|Contents/MacOS|\.framework|^root|^_' | awk 'NR>1 {printf \"%s %s cpu:%s %s\n\", \$1, \$2, \$3, \$11}' | head -20"
```

Run these as three separate Bash calls (not chained) so partial failures are visible.

Present as:

```
Remote: __REMOTE_ALIAS__ (__REMOTE_HOST__)
Uptime:  {uptime output}
Disk:    {df / output}

Active user processes:
{process list}
```

### Execute Command (arguments provided)

Run the arguments as a shell command on the remote server:

```bash
ssh __REMOTE_USER__@__REMOTE_HOST__ "{arguments}"
```

Return output as-is. If the command fails, show the exit code and stderr.
