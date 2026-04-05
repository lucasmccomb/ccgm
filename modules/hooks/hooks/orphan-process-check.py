#!/usr/bin/env python3
"""
Check for orphaned test worker processes (vitest, jest) at session start.

Orphaned workers occur when a Claude Code session exits mid-test-run. The forked
worker processes get re-parented to PID 1 (launchd) and run indefinitely, consuming
RAM and CPU.

This hook runs during startup and warns if orphans are found.
"""

import json
import os
import subprocess
import sys


def find_orphaned_test_workers():
    """Find node processes with PPID 1 that look like test workers."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,rss,command"],
            capture_output=True, text=True, timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    orphans = []
    for line in result.stdout.strip().split("\n")[1:]:  # skip header
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue

        pid, ppid, rss_kb, command = parts[0], parts[1], parts[2], parts[3]

        # Only orphaned processes (PPID 1)
        if ppid != "1":
            continue

        # Only node processes that look like test workers
        test_patterns = ["vitest", "jest-worker", "jest_worker", "test-worker"]
        if not any(p in command.lower() for p in test_patterns):
            continue

        try:
            orphans.append({
                "pid": int(pid),
                "rss_mb": int(rss_kb) / 1024,
                "command": command[:80]
            })
        except ValueError:
            continue

    return orphans


def main():
    orphans = find_orphaned_test_workers()

    if not orphans:
        sys.exit(0)

    total_mb = sum(o["rss_mb"] for o in orphans)
    pids = [str(o["pid"]) for o in orphans]

    # Output warning via hook result
    msg = (
        f"WARNING: {len(orphans)} orphaned test worker(s) found "
        f"({total_mb:.0f} MB RAM). "
        f"PIDs: {', '.join(pids[:10])}. "
        f"Run: kill {' '.join(pids[:10])}"
    )

    print(json.dumps({
        "decision": "approve",
        "reason": msg
    }))


if __name__ == "__main__":
    main()
