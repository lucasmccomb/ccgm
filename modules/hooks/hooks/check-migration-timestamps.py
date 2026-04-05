#!/usr/bin/env python3
"""
PreToolUse:Bash hook to prevent duplicate Supabase migration timestamps.

BLOCKS git commit when migration files have duplicate numeric prefixes.
Duplicate timestamps break `supabase db push` because the CLI can't distinguish
files that share the same timestamp - one gets applied and the other gets stuck
as "local only" permanently.

Only runs when:
1. The command is a git commit
2. A supabase/migrations/ directory exists in the working directory
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    # Only handle Bash commands
    if data.get("tool_name", "") != "Bash":
        return

    command = data.get("tool_input", {}).get("command", "")

    # Only check git commit commands
    if not re.search(r"\bgit\s+commit\b", command):
        return

    # Check if we're in a git repo with supabase/migrations/
    migrations_dir = None
    for candidate in ["supabase/migrations", "supabase/migrations/"]:
        if os.path.isdir(candidate):
            migrations_dir = candidate
            break

    if not migrations_dir:
        return

    # Check ALL migration files for duplicate timestamps
    try:
        all_files = sorted(os.listdir(migrations_dir))
    except OSError:
        return

    sql_files = [f for f in all_files if f.endswith(".sql")]
    timestamps = []
    for f in sql_files:
        match = re.match(r"^(\d+)", f)
        if match:
            timestamps.append(match.group(1))

    # Find duplicates
    counts = Counter(timestamps)
    duplicates = {ts: count for ts, count in counts.items() if count > 1}

    if not duplicates:
        return

    # Build error message
    dup_details = []
    for ts in sorted(duplicates.keys()):
        files = [f for f in sql_files if f.startswith(ts)]
        dup_details.append(f"  Timestamp {ts} used by {duplicates[ts]} files:")
        for f in files:
            dup_details.append(f"    - {f}")

    error_msg = (
        "BLOCKED: Duplicate Supabase migration timestamps detected.\n"
        "Duplicate timestamps break `supabase db push` - the CLI can't distinguish files\n"
        "that share the same numeric prefix. Rename one file to a unique timestamp.\n\n"
        + "\n".join(dup_details)
        + "\n\nFix: rename one file in each group to increment the timestamp by 1 "
        "(e.g., 20260325900000 -> 20260325900001)."
    )

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": error_msg
        }
    }, sys.stdout)


if __name__ == "__main__":
    main()
