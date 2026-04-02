#!/usr/bin/env python3
"""
PostToolUse:Bash hook for multi-agent issue tracking.

All tracking CSV mutations happen here, AFTER the command succeeds.
This prevents orphaned claims from failed commands.

Intercepts:
- git checkout -b {N}-*     : Register claim for issue N
- git commit -m "#N: ..."   : Update heartbeat (throttled to 30 min)
- gh pr create              : Update status to pr-created
- gh pr merge               : Update status to merged
- gh issue close            : Update status to closed

PostToolUse input schema (verified empirically):
{
    "tool_name": "Bash",
    "tool_input": {"command": "...", "description": "..."},
    "tool_response": {"stdout": "...", "stderr": "...", "interrupted": false},
    "cwd": "/path/to/working/dir",
    ...
}
"""

import json
import os
import re
import subprocess
import sys

# Import tracking module
sys.path.insert(0, os.path.expanduser("~/.claude/lib"))

LOG_REPO_DIR = os.path.expanduser("~/code/lem-agent-logs")


def is_multi_clone_repo(cwd=None):
    """Check if directory has .env.clone (multi-clone repo)."""
    wd = cwd or os.getcwd()
    return os.path.isfile(os.path.join(wd, ".env.clone"))


def is_log_repo(cwd=None):
    """Check if we're in the log repo (skip heartbeats for log commits)."""
    wd = cwd or os.getcwd()
    try:
        return os.path.realpath(wd).startswith(os.path.realpath(LOG_REPO_DIR))
    except Exception:
        return False


def get_repo_name(cwd=None):
    """Get repo name from git remote."""
    wd = cwd or os.getcwd()
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, cwd=wd,
        )
        if result.returncode == 0:
            name = os.path.basename(result.stdout.strip())
            return name.removesuffix(".git")
    except Exception:
        pass
    return None


def extract_issue_from_branch_cmd(command):
    """Extract issue number from git checkout -b {N}-* command."""
    match = re.search(r"git\s+checkout\s+-b\s+(\d+)-", command)
    if match:
        return match.group(1)
    return None


def extract_issue_from_commit_msg(command):
    """Extract issue number from git commit -m '#N: ...' command."""
    match = re.search(r'-m\s+["\']?#(\d+):', command)
    if match:
        return match.group(1)
    return None


def extract_branch_name(command):
    """Extract branch name from git checkout -b command."""
    match = re.search(r"git\s+checkout\s+-b\s+(\S+)", command)
    if match:
        return match.group(1)
    return None


def extract_pr_number(stdout):
    """Extract PR number from gh pr create output."""
    # gh pr create outputs a URL like https://github.com/user/repo/pull/123
    match = re.search(r"/pull/(\d+)", stdout)
    if match:
        return match.group(1)
    return None


def get_issue_title(issue_num, cwd=None):
    """Fetch issue title from GitHub (best-effort)."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--json", "title", "--jq", ".title"],
            capture_output=True, text=True, timeout=10,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def get_current_branch(cwd=None):
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def extract_issue_from_branch_name(branch):
    """Extract issue number from branch name like 42-fix-auth."""
    if branch:
        match = re.match(r"^(\d+)-", branch)
        if match:
            return match.group(1)
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    cwd = data.get("cwd", os.getcwd())

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "").strip()
    stdout = tool_response.get("stdout", "")
    stderr = tool_response.get("stderr", "")
    interrupted = tool_response.get("interrupted", False)

    if not command or interrupted:
        sys.exit(0)

    # Early exit: not a multi-clone repo
    if not is_multi_clone_repo(cwd):
        sys.exit(0)

    try:
        from agent_tracking import (
            claim_issue, update_status, update_heartbeat,
            check_claim, get_agent_id, get_repo_name as at_get_repo_name,
        )

        agent_id = get_agent_id(cwd)
        repo = get_repo_name(cwd)
        if not repo:
            sys.exit(0)

        # --- git checkout -b {N}-* : Register claim ---
        if re.match(r"git\s+checkout\s+-b\s+\d+-", command):
            issue_num = extract_issue_from_branch_cmd(command)
            branch = extract_branch_name(command)
            if issue_num:
                # Check if we already have this claim (idempotent)
                existing_agent, _ = check_claim(repo, issue_num)
                if existing_agent == agent_id:
                    sys.exit(0)  # Already claimed by us

                title = get_issue_title(issue_num, cwd)
                claim_issue(
                    repo, issue_num,
                    agent_id=agent_id,
                    title=title,
                    branch=branch or "",
                )

        # --- git commit -m "#N: ..." : Heartbeat ---
        elif re.match(r"git\s+commit(\s|$)", command) and not is_log_repo(cwd):
            issue_num = extract_issue_from_commit_msg(command)
            if not issue_num:
                # Try to get issue from branch name
                branch = get_current_branch(cwd)
                issue_num = extract_issue_from_branch_name(branch)

            if issue_num:
                # Also transition from claimed -> in-progress on first commit
                existing_agent, status = check_claim(repo, issue_num)
                if existing_agent == agent_id and status == "claimed":
                    update_status(repo, issue_num, "in-progress", agent_id=agent_id)
                else:
                    update_heartbeat(repo, issue_num, agent_id=agent_id)

        # --- gh pr create : Update to pr-created ---
        elif re.match(r"gh\s+pr\s+create", command):
            branch = get_current_branch(cwd)
            issue_num = extract_issue_from_branch_name(branch)
            pr_num = extract_pr_number(stdout)
            if issue_num:
                update_status(
                    repo, issue_num, "pr-created",
                    agent_id=agent_id, pr=pr_num,
                )

        # --- gh pr merge : Update to merged ---
        elif re.match(r"gh\s+pr\s+merge", command):
            branch = get_current_branch(cwd)
            issue_num = extract_issue_from_branch_name(branch)
            if issue_num:
                update_status(repo, issue_num, "merged", agent_id=agent_id)

        # --- gh issue close : Update to closed ---
        elif re.match(r"gh\s+issue\s+close\s+(\d+)", command):
            match = re.search(r"gh\s+issue\s+close\s+(\d+)", command)
            if match:
                issue_num = match.group(1)
                update_status(repo, issue_num, "closed", agent_id=agent_id)

    except Exception as e:
        # Never block on tracking errors - write warning to stderr
        sys.stderr.write(f"agent-tracking-post: {e}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
