#!/usr/bin/env python3
"""
Discover active Claude Code CLI sessions on this machine.

Uses ps + lsof + git to find all running claude CLI sessions with their
working directory, repo, and branch context. No files, no daemons - just
reads live OS state. Process exit = session gone, no stale data possible.

Usage as library:
    from agent_sessions import get_active_sessions
    sessions = get_active_sessions()
    # [{pid, tty, uptime, cwd, repo, branch, agent_id}, ...]

Usage as CLI:
    python3 agent_sessions.py          # JSON output
    python3 agent_sessions.py --text   # Human-readable table
    python3 agent_sessions.py --repo habitpro-ai  # Filter by repo
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Core discovery
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: str | None = None, timeout: int = 5) -> str:
    """Run a command, return stdout or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_claude_pids() -> list[tuple[int, str, str]]:
    """
    Return list of (pid, tty, etime) for running claude CLI processes.

    Filters out Claude Desktop (Electron app) and helper processes.
    Matches only the bare 'claude' command or 'claude /startup' etc.
    """
    ps_out = _run(["ps", "-eo", "pid,tty,etime,command"])
    pids: list[tuple[int, str, str]] = []
    for line in ps_out.splitlines():
        # Match lines where the command is exactly 'claude' (with optional args)
        # Exclude: Claude.app, Claude Helper, grep, python running this script
        m = re.search(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+claude(\s|$)", line)
        if not m:
            continue
        full_line = line.strip()
        # Exclude Electron app and helpers
        if any(skip in full_line for skip in ["Claude.app", "Claude Helper", "Claude.framework"]):
            continue
        pid, tty, etime = m.group(1), m.group(2), m.group(3)
        pids.append((int(pid), tty, etime))
    return pids


def _get_cwd(pid: int) -> str | None:
    """Get the current working directory of a process via lsof."""
    out = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=5)
    for line in out.splitlines():
        if line.startswith("n"):
            path = line[1:]
            if os.path.isdir(path):
                return path
    return None


def _get_git_context(cwd: str) -> tuple[str | None, str | None]:
    """Return (repo_name, branch) for a directory, or (None, None)."""
    branch = _run(["git", "-C", cwd, "branch", "--show-current"])
    if not branch:
        return None, None
    remote_url = _run(["git", "-C", cwd, "remote", "get-url", "origin"])
    repo_name = os.path.basename(remote_url) if remote_url else None
    if repo_name and repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    repo = repo_name
    return repo, branch


def _get_agent_id(cwd: str) -> str | None:
    """
    Derive agent identity from .env.clone or directory name pattern.

    Workspace model: habitpro-ai-w1-c2 -> agent-w1-c2
    Flat clone model: habitpro-ai-3 -> agent-3
    """
    env_clone = os.path.join(cwd, ".env.clone")
    if os.path.isfile(env_clone):
        try:
            with open(env_clone) as f:
                for line in f:
                    if line.startswith("AGENT_ID="):
                        return line.strip().split("=", 1)[1]
        except Exception:
            pass

    dirname = os.path.basename(cwd)
    # Workspace model pattern: *-wN-cN
    m = re.search(r"w\d+-c\d+$", dirname)
    if m:
        return f"agent-{m.group()}"
    # Flat clone model pattern: *-N (trailing number)
    m = re.search(r"-(\d+)$", dirname)
    if m:
        return f"agent-{m.group(1)}"
    return None


def get_active_sessions(repo_filter: str | None = None, exclude_cwd: str | None = None) -> list[dict]:
    """
    Return list of active Claude Code CLI sessions on this machine.

    Args:
        repo_filter: If set, only return sessions for this repo name.
        exclude_cwd: If set, exclude the session at this working directory
                     (used to exclude the current session from sibling lists).

    Returns:
        List of dicts:
        {
            "pid":      int,    # Process ID
            "tty":      str,    # Terminal (e.g. ttys003, ?? for background)
            "uptime":   str,    # Elapsed time (e.g. "01-02:30:45", "15:30")
            "cwd":      str,    # Working directory
            "repo":     str,    # Git repo name (or None)
            "branch":   str,    # Current git branch (or None)
            "agent_id": str,    # Derived agent ID (or None)
        }
    """
    sessions: list[dict] = []
    my_cwd = os.path.realpath(exclude_cwd) if exclude_cwd else None

    for pid, tty, etime in _get_claude_pids():
        cwd = _get_cwd(pid)
        if not cwd:
            continue

        # Normalize for comparison
        real_cwd = os.path.realpath(cwd)
        if my_cwd and real_cwd == my_cwd:
            continue  # Skip current session

        repo, branch = _get_git_context(cwd)

        if repo_filter and repo != repo_filter:
            continue

        sessions.append({
            "pid":      pid,
            "tty":      tty,
            "uptime":   etime,
            "cwd":      cwd,
            "repo":     repo,
            "branch":   branch,
            "agent_id": _get_agent_id(cwd),
        })

    return sessions


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_sessions_text(sessions: list[dict], header: bool = True) -> str:
    """Format sessions as a human-readable table for dashboard display."""
    if not sessions:
        return "  (none)"

    lines = []
    for s in sessions:
        pid_str = str(s["pid"])
        repo = s["repo"] or "(no repo)"
        branch = s["branch"] or "(no branch)"
        agent = s["agent_id"] or "(unknown)"
        uptime = s["uptime"]
        tty = s["tty"]
        cwd = s["cwd"]

        if s["repo"]:
            lines.append(
                f"  PID {pid_str:6} | {repo:25} | branch: {branch:30} | "
                f"up: {uptime:12} | {tty}"
            )
        else:
            lines.append(
                f"  PID {pid_str:6} | (no repo) {cwd:40} | up: {uptime:12} | {tty}"
            )
    return "\n".join(lines)


def sessions_by_repo(sessions: list[dict]) -> dict[str, list[dict]]:
    """Group sessions by repo name. Returns {repo: [sessions]}."""
    grouped = {}
    for s in sessions:
        key = s["repo"] or "(no repo)"
        grouped.setdefault(key, []).append(s)
    return grouped


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="List active Claude Code CLI sessions on this machine."
    )
    parser.add_argument("--text", action="store_true", help="Human-readable output")
    parser.add_argument("--repo", help="Filter by repo name")
    parser.add_argument("--exclude-cwd", help="Exclude session at this CWD")
    args = parser.parse_args()

    sessions = get_active_sessions(
        repo_filter=args.repo,
        exclude_cwd=args.exclude_cwd,
    )

    if args.text:
        print(format_sessions_text(sessions))
    else:
        print(json.dumps(sessions, indent=2))


if __name__ == "__main__":
    main()
