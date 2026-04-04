# Remote Server Access

A remote server is configured for SSH access. Use the `/onremote` command or direct `ssh` via the Bash tool to run operations on it.

## Connection

The remote host and credentials are baked into `~/.claude/commands/onremote.md` at install time. Use SSH via Bash:

```bash
ssh {remote-user}@{remote-host} "command"
```

For file transfers use `scp` or `rsync`.

## When to Use Remote Access

- Checking on long-running services or background processes
- Restarting services that have crashed or stalled
- Viewing logs from remote processes
- Running maintenance tasks (disk cleanup, log rotation)
- Running commands that require the remote machine's hardware or environment

## Rules

- Use `/onremote` for status checks and single commands
- Never start interactive sessions (`ssh -t` with a shell) - output-only commands only
- Do not run destructive operations (rm, shutdown, kill -9) without explicit user confirmation
- For multi-step operations, chain commands with `&&` in a single SSH call rather than multiple round-trips
- Prefer reading log files (`tail -n 50 /path/to/log`) over running verbose diagnostic tools
