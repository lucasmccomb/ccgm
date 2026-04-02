#!/usr/bin/env python3
"""
Multi-agent issue tracking system.

Provides structured issue lifecycle tracking via a single CSV file per repo
in the agent log repository. Replaces the label-based claiming system.

Storage: ~/code/lem-agent-logs/{repo}/tracking.csv
Format: CSV with fields: issue,agent,status,branch,pr,epic,title,claimed_at,updated_at
Concurrency: Standard git flow (commit, pull --rebase, push). Different-row
edits auto-resolve via rebase.

Usage as CLI:
    python agent_tracking.py claim <repo> <issue> [--title "..."] [--epic N]
    python agent_tracking.py check <repo> <issue>
    python agent_tracking.py update <repo> <issue> --status <status> [--pr N]
    python agent_tracking.py release <repo> <issue>
    python agent_tracking.py list [--repo <repo>] [--status <status>] [--agent <id>]
    python agent_tracking.py gc [--days N]
    python agent_tracking.py import <repo>
    python agent_tracking.py init <repo>

Usage as import:
    from agent_tracking import claim_issue, check_claim, update_status
"""

import argparse
import csv
import io
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "issue", "agent", "status", "branch", "pr",
    "epic", "title", "claimed_at", "updated_at",
]

ACTIVE_STATUSES = {"claimed", "in-progress", "pr-created", "blocked"}
TERMINAL_STATUSES = {"merged", "closed", "released"}
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES

LOG_REPO_DIR = os.path.expanduser("~/code/lem-agent-logs")

# ---------------------------------------------------------------------------
# Agent identity helpers
# ---------------------------------------------------------------------------

def get_agent_id(working_dir=None):
    """Derive agent ID from the working directory or .env.clone."""
    wd = working_dir or os.getcwd()

    # Try .env.clone first
    env_clone = os.path.join(wd, ".env.clone")
    if os.path.isfile(env_clone):
        with open(env_clone) as f:
            for line in f:
                if line.startswith("AGENT_ID="):
                    return line.strip().split("=", 1)[1]

    # Workspace model: directory name ends with w{N}-c{M}
    import re
    basename = os.path.basename(wd)
    wc = re.search(r"w(\d+)-c(\d+)$", basename)
    if wc:
        return f"agent-w{wc.group(1)}-c{wc.group(2)}"

    # Flat clone model: directory name ends with -{N}
    num = re.search(r"-(\d+)$", basename)
    if num:
        return f"agent-{num.group(1)}"

    return "agent-0"


def get_repo_name(working_dir=None):
    """Derive repo name from git remote origin URL."""
    wd = working_dir or os.getcwd()
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, cwd=wd,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            name = os.path.basename(url)
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return None


def is_multi_clone_repo(working_dir=None):
    """Check if the current directory is a multi-clone repo (has .env.clone)."""
    wd = working_dir or os.getcwd()
    return os.path.isfile(os.path.join(wd, ".env.clone"))


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def get_tracking_path(repo):
    """Return the path to tracking.csv for a repo."""
    return os.path.join(LOG_REPO_DIR, repo, "tracking.csv")


def read_tracking(repo):
    """Read tracking.csv and return a list of dicts."""
    path = get_tracking_path(repo)
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def write_tracking(repo, rows):
    """Write a list of dicts to tracking.csv."""
    path = get_tracking_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def now_iso():
    """Return current local time as ISO 8601 string (minute precision)."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# Git operations on the log repo
# ---------------------------------------------------------------------------

def commit_and_push(agent_id, message):
    """Commit tracking changes to the log repo and push.

    Uses standard git flow: add, commit, pull --rebase, push.
    Returns True on success, False on failure (non-blocking).
    """
    try:
        cmds = [
            ["git", "add", "-A"],
            ["git", "commit", "-m", f"{agent_id}: {message}"],
            ["git", "pull", "--rebase"],
            ["git", "push"],
        ]
        for cmd in cmds:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                cwd=LOG_REPO_DIR,
            )
            # git commit returns 1 if nothing to commit - that's ok
            if result.returncode != 0 and cmd[1] != "commit":
                sys.stderr.write(
                    f"WARNING: tracking git {cmd[1]} failed: {result.stderr.strip()}\n"
                )
                return False
        return True
    except Exception as e:
        sys.stderr.write(f"WARNING: tracking commit/push failed: {e}\n")
        return False


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def claim_issue(repo, issue, agent_id=None, title="", epic="", branch=""):
    """Claim an issue. Returns (success: bool, message: str)."""
    agent_id = agent_id or get_agent_id()
    issue = str(issue)

    rows = read_tracking(repo)

    # Check for existing active claim on this issue
    for row in rows:
        if row["issue"] == issue and row["status"] in ACTIVE_STATUSES:
            if row["agent"] == agent_id:
                return False, f"You already have issue #{issue} claimed"
            return False, f"Issue #{issue} is already claimed by {row['agent']}"

    # Add claim
    rows.append({
        "issue": issue,
        "agent": agent_id,
        "status": "claimed",
        "branch": branch,
        "pr": "",
        "epic": str(epic) if epic else "",
        "title": title,
        "claimed_at": now_iso(),
        "updated_at": now_iso(),
    })

    write_tracking(repo, rows)
    commit_and_push(agent_id, f"claim #{issue}")
    return True, f"Claimed issue #{issue}"


def update_status(repo, issue, status, agent_id=None, pr=None, branch=None):
    """Update the status of a claimed issue. Returns (success, message)."""
    agent_id = agent_id or get_agent_id()
    issue = str(issue)

    if status not in ALL_STATUSES:
        return False, f"Invalid status: {status}. Valid: {', '.join(sorted(ALL_STATUSES))}"

    rows = read_tracking(repo)
    updated = False

    for row in rows:
        if row["issue"] == issue and row["agent"] == agent_id and row["status"] in ACTIVE_STATUSES:
            row["status"] = status
            row["updated_at"] = now_iso()
            if pr is not None:
                row["pr"] = str(pr)
            if branch is not None:
                row["branch"] = branch
            updated = True
            break

    if not updated:
        return False, f"No active claim found for issue #{issue} by {agent_id}"

    write_tracking(repo, rows)
    commit_and_push(agent_id, f"update #{issue} -> {status}")
    return True, f"Updated issue #{issue} to {status}"


def update_heartbeat(repo, issue, agent_id=None, throttle_minutes=30):
    """Update the heartbeat (updated_at) for an issue, throttled.

    Only updates if the current updated_at is older than throttle_minutes.
    Returns (updated: bool, message: str).
    """
    agent_id = agent_id or get_agent_id()
    issue = str(issue)

    rows = read_tracking(repo)
    threshold = datetime.now() - timedelta(minutes=throttle_minutes)

    for row in rows:
        if row["issue"] == issue and row["agent"] == agent_id and row["status"] in ACTIVE_STATUSES:
            try:
                last_updated = datetime.strptime(row["updated_at"], "%Y-%m-%dT%H:%M")
                if last_updated > threshold:
                    return False, "Heartbeat throttled (too recent)"
            except ValueError:
                pass  # Can't parse, just update

            row["updated_at"] = now_iso()
            write_tracking(repo, rows)
            # Don't commit/push for heartbeats - they'll be included in the next
            # regular log repo commit to avoid excessive pushes
            return True, f"Heartbeat updated for #{issue}"

    return False, f"No active claim found for issue #{issue}"


def release_issue(repo, issue, agent_id=None):
    """Release a claimed issue. Returns (success, message)."""
    return update_status(repo, issue, "released", agent_id)


def check_claim(repo, issue):
    """Check if an issue is claimed. Returns (agent_id, status) or (None, None)."""
    issue = str(issue)
    rows = read_tracking(repo)
    for row in rows:
        if row["issue"] == issue and row["status"] in ACTIVE_STATUSES:
            return row["agent"], row["status"]
    return None, None


def list_claims(repo=None, status=None, agent=None):
    """List claims, optionally filtered. Returns list of dicts."""
    results = []

    if repo:
        repos = [repo]
    else:
        # Find all repos with tracking.csv
        repos = []
        if os.path.isdir(LOG_REPO_DIR):
            for entry in sorted(os.listdir(LOG_REPO_DIR)):
                tracking = os.path.join(LOG_REPO_DIR, entry, "tracking.csv")
                if os.path.isfile(tracking):
                    repos.append(entry)

    for r in repos:
        rows = read_tracking(r)
        for row in rows:
            if status and row["status"] != status:
                continue
            if agent and row["agent"] != agent:
                continue
            row["_repo"] = r
            results.append(row)

    return results


def gc_stale(repo=None, days=1):
    """Find stale claims (active status + old updated_at). Returns list of stale rows."""
    threshold = datetime.now() - timedelta(days=days)
    stale = []

    claims = list_claims(repo=repo)
    for row in claims:
        if row["status"] not in ACTIVE_STATUSES:
            continue
        try:
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%dT%H:%M")
            if updated < threshold:
                row["_stale_hours"] = int((datetime.now() - updated).total_seconds() / 3600)
                stale.append(row)
        except ValueError:
            # Can't parse date - consider it stale
            row["_stale_hours"] = "unknown"
            stale.append(row)

    return stale


def import_from_labels(repo, agent_id=None):
    """Import existing GitHub issues with agent-* labels into tracking.csv.

    Scans for open issues with in-progress or agent-* labels and creates
    tracking entries for them.
    """
    agent_id = agent_id or get_agent_id()
    imported = 0

    try:
        # Get all open issues with labels
        result = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "100",
             "--json", "number,title,labels"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return 0, f"Failed to list issues: {result.stderr.strip()}"

        import json
        issues = json.loads(result.stdout)
        rows = read_tracking(repo)
        existing_issues = {row["issue"] for row in rows if row["status"] in ACTIVE_STATUSES}

        for issue in issues:
            issue_num = str(issue["number"])
            if issue_num in existing_issues:
                continue

            labels = [l["name"] for l in issue.get("labels", [])]
            # Find agent label
            agent_label = None
            for label in labels:
                if label.startswith("agent-"):
                    agent_label = label
                    break

            if agent_label or "in-progress" in labels:
                status = "in-progress" if "in-progress" in labels else "claimed"
                rows.append({
                    "issue": issue_num,
                    "agent": agent_label or agent_id,
                    "status": status,
                    "branch": "",
                    "pr": "",
                    "epic": "",
                    "title": issue["title"],
                    "claimed_at": now_iso(),
                    "updated_at": now_iso(),
                })
                imported += 1

        if imported > 0:
            write_tracking(repo, rows)
            commit_and_push(agent_id, f"import {imported} issues from labels")

        return imported, f"Imported {imported} issues"

    except Exception as e:
        return 0, f"Import failed: {e}"


def init_tracking(repo):
    """Create tracking.csv with header row for a repo."""
    path = get_tracking_path(repo)
    if os.path.isfile(path):
        return False, f"tracking.csv already exists for {repo}"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()

    return True, f"Created tracking.csv for {repo}"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_claims_table(claims, show_repo=False):
    """Format claims as a readable table string."""
    if not claims:
        return "  (no claims)"

    lines = []
    if show_repo:
        header = f"  {'Repo':<20} {'Issue':>6} {'Agent':<16} {'Status':<14} {'Branch':<30} {'PR':>4} {'Updated'}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for c in claims:
            repo_name = c.get("_repo", "")
            lines.append(
                f"  {repo_name:<20} #{c['issue']:>5} {c['agent']:<16} {c['status']:<14} "
                f"{c.get('branch', ''):<30} {c.get('pr', ''):>4} {c.get('updated_at', '')}"
            )
    else:
        header = f"  {'Issue':>6} {'Agent':<16} {'Status':<14} {'Branch':<30} {'PR':>4} {'Updated'}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for c in claims:
            lines.append(
                f"  #{c['issue']:>5} {c['agent']:<16} {c['status']:<14} "
                f"{c.get('branch', ''):<30} {c.get('pr', ''):>4} {c.get('updated_at', '')}"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent issue tracking",
        prog="agent-tracking",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # claim
    p = sub.add_parser("claim", help="Claim an issue")
    p.add_argument("repo", help="Repo name (e.g., darkly-suite)")
    p.add_argument("issue", type=int, help="Issue number")
    p.add_argument("--title", default="", help="Issue title")
    p.add_argument("--epic", type=int, default=None, help="Parent epic number")
    p.add_argument("--branch", default="", help="Branch name")

    # update
    p = sub.add_parser("update", help="Update issue status")
    p.add_argument("repo", help="Repo name")
    p.add_argument("issue", type=int, help="Issue number")
    p.add_argument("--status", required=True, help="New status")
    p.add_argument("--pr", type=int, default=None, help="PR number")
    p.add_argument("--branch", default=None, help="Branch name")

    # release
    p = sub.add_parser("release", help="Release an issue")
    p.add_argument("repo", help="Repo name")
    p.add_argument("issue", type=int, help="Issue number")

    # check
    p = sub.add_parser("check", help="Check if an issue is claimed")
    p.add_argument("repo", help="Repo name")
    p.add_argument("issue", type=int, help="Issue number")

    # list
    p = sub.add_parser("list", help="List claims")
    p.add_argument("--repo", default=None, help="Filter by repo")
    p.add_argument("--status", default=None, help="Filter by status")
    p.add_argument("--agent", default=None, help="Filter by agent")

    # gc
    p = sub.add_parser("gc", help="Find stale claims")
    p.add_argument("--repo", default=None, help="Filter by repo")
    p.add_argument("--days", type=int, default=1, help="Stale threshold in days")

    # import
    p = sub.add_parser("import", help="Import issues from GitHub labels")
    p.add_argument("repo", help="Repo name")

    # init
    p = sub.add_parser("init", help="Initialize tracking.csv for a repo")
    p.add_argument("repo", help="Repo name")

    args = parser.parse_args()

    if args.command == "claim":
        ok, msg = claim_issue(args.repo, args.issue, title=args.title,
                              epic=args.epic or "", branch=args.branch)
        print(msg)
        sys.exit(0 if ok else 1)

    elif args.command == "update":
        ok, msg = update_status(args.repo, args.issue, args.status,
                                pr=args.pr, branch=args.branch)
        print(msg)
        sys.exit(0 if ok else 1)

    elif args.command == "release":
        ok, msg = release_issue(args.repo, args.issue)
        print(msg)
        sys.exit(0 if ok else 1)

    elif args.command == "check":
        agent, status = check_claim(args.repo, args.issue)
        if agent:
            print(f"Issue #{args.issue} is claimed by {agent} (status: {status})")
        else:
            print(f"Issue #{args.issue} is unclaimed")

    elif args.command == "list":
        claims = list_claims(repo=args.repo, status=args.status, agent=args.agent)
        show_repo = args.repo is None
        print(format_claims_table(claims, show_repo=show_repo))

    elif args.command == "gc":
        stale = gc_stale(repo=args.repo, days=args.days)
        if stale:
            print(f"Found {len(stale)} stale claims:")
            for s in stale:
                repo_name = s.get("_repo", "")
                hours = s.get("_stale_hours", "?")
                print(f"  WARNING: {s['agent']} has stale claim on #{s['issue']} "
                      f"in {repo_name} (status: {s['status']}, stale for {hours}h)")
        else:
            print("No stale claims found")

    elif args.command == "import":
        count, msg = import_from_labels(args.repo)
        print(msg)
        sys.exit(0 if count >= 0 else 1)

    elif args.command == "init":
        ok, msg = init_tracking(args.repo)
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
