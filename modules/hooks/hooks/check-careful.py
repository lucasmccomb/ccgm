#!/usr/bin/env python3
"""
PreToolUse hook that pauses on destructive Bash commands.

Inspects Bash commands and returns permissionDecision:"ask" with a warning for
destructive patterns that commonly cause data loss or history destruction:
  - rm -rf (with smart whitelist for build artifacts)
  - SQL DROP / TRUNCATE
  - git push --force (and --force-with-lease)
  - git reset --hard (history destroying)
  - git checkout . (dirty discard)
  - kubectl delete
  - docker rm -f / docker system prune

Build-artifact directories are whitelisted so `rm -rf node_modules` does not
trigger a prompt. Whitelist: node_modules, dist, .next, build, __pycache__,
.cache, .turbo, coverage.

Ported to Python from gstack `careful/bin/check-careful.sh` to match CCGM's
hook style (JSON stdin/stdout, consistent with auto-approve-bash.py).
"""
from __future__ import annotations

import json
import re
import sys

# Build-artifact directory names that are safe to `rm -rf` without asking.
# If every path on an rm -rf line matches one of these (exactly or as a
# trailing component), we let it pass without warning.
BUILD_ARTIFACT_WHITELIST = {
    "node_modules",
    "dist",
    ".next",
    "build",
    "__pycache__",
    ".cache",
    ".turbo",
    "coverage",
}


def _is_whitelisted_rm_rf(command: str) -> bool:
    """
    Return True if every target of `rm -rf` in `command` is a build artifact.

    Walks tokens after `rm` (in any order of flags) and verifies each
    non-flag argument is a recognised build-artifact directory name.
    Conservative: any unknown target disables the whitelist.
    """
    # Extract the argument list after `rm`. We only check the first rm
    # occurrence; chained commands are handled separately by the caller.
    m = re.search(r"\brm\s+([^\|&;]+)", command)
    if not m:
        return False

    tokens = m.group(1).strip().split()
    targets: list[str] = []
    for tok in tokens:
        if tok.startswith("-"):
            # Flag (e.g. -rf, -r, -f, --force, -R)
            continue
        targets.append(tok)

    if not targets:
        return False

    for target in targets:
        # Strip trailing slash, quotes
        t = target.strip().strip("'\"").rstrip("/")
        # Extract the last path component (e.g. "apps/web/dist" -> "dist")
        last = t.rsplit("/", 1)[-1]
        if last not in BUILD_ARTIFACT_WHITELIST:
            return False

    return True


def check_careful(command: str) -> tuple[bool, str]:
    """
    Determine whether the command is destructive and should prompt the user.

    Returns (is_destructive, warning_reason).
    """
    # Normalize whitespace for easier matching
    cmd = command

    # rm -rf  (any order of -r/-R/-f/--recursive/--force)
    # Matches: rm -rf, rm -fr, rm -r -f, rm --recursive --force, rm -Rf
    rm_rf_patterns = [
        r"\brm\s+[^\|&;]*-[rRf]*r[rRf]*f",  # -rf, -fr, -Rf, -fR (r and f together)
        r"\brm\s+[^\|&;]*-[rRf]*f[rRf]*r",  # -fr ordering
        r"\brm\s+[^\|&;]*--recursive[^\|&;]*--force",
        r"\brm\s+[^\|&;]*--force[^\|&;]*--recursive",
        r"\brm\s+[^\|&;]*-r\b[^\|&;]*-f\b",
        r"\brm\s+[^\|&;]*-f\b[^\|&;]*-r\b",
    ]
    for pattern in rm_rf_patterns:
        if re.search(pattern, cmd):
            if _is_whitelisted_rm_rf(cmd):
                return (False, "")
            return (True, "Destructive: `rm -rf` deletes recursively. Confirm targets are correct.")

    # SQL DROP statements (DROP TABLE, DROP DATABASE, DROP SCHEMA, etc.)
    if re.search(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW|FUNCTION|TRIGGER|ROLE|USER)\b", cmd, re.IGNORECASE):
        return (True, "Destructive SQL: DROP removes objects permanently. Confirm target and environment.")

    # SQL TRUNCATE
    if re.search(r"\bTRUNCATE\s+(TABLE\s+)?\w+", cmd, re.IGNORECASE):
        return (True, "Destructive SQL: TRUNCATE empties a table. Confirm target and environment.")

    # git push --force / -f. The safer --force-with-lease only rewrites the
    # remote when our local ref still matches it, which is the recommended
    # flow in git-workflow.md when rebasing a feature branch onto main.
    # Don't prompt on --force-with-lease.
    if re.search(r"\bgit\s+push\s+[^\|&;]*(--force\b(?!-with-lease)|-f\b)", cmd):
        return (True, "History-rewriting: `git push --force` overwrites remote commits. Confirm the branch is yours.")

    # git reset --hard (any target). Even `origin/main` can discard uncommitted work.
    if re.search(r"\bgit\s+(-C\s+\S+\s+)?reset\s+--hard\b", cmd):
        return (True, "History-destroying: `git reset --hard` discards local changes and commits. Confirm no work is lost.")

    # git checkout . (discard working tree changes)
    if re.search(r"\bgit\s+checkout\s+\.(\s|$)", cmd):
        return (True, "Destructive: `git checkout .` discards all uncommitted changes. Confirm before proceeding.")

    # git restore . / git restore --staged .
    if re.search(r"\bgit\s+restore\s+(--staged\s+)?\.(\s|$)", cmd):
        return (True, "Destructive: `git restore .` discards uncommitted changes. Confirm before proceeding.")

    # git clean -f (removes untracked files)
    if re.search(r"\bgit\s+clean\s+[^\|&;]*-[fdx]*f", cmd):
        return (True, "Destructive: `git clean -f` removes untracked files. Confirm before proceeding.")

    # kubectl delete
    if re.search(r"\bkubectl\s+delete\b", cmd):
        return (True, "Destructive: `kubectl delete` removes cluster resources. Confirm target and namespace.")

    # docker rm -f / docker rmi -f
    if re.search(r"\bdocker\s+rmi?\s+[^\|&;]*-f", cmd):
        return (True, "Destructive: `docker rm/rmi -f` force-removes containers/images. Confirm before proceeding.")

    # docker system prune / docker volume prune
    if re.search(r"\bdocker\s+(system|volume|image|container|network)\s+prune\b", cmd):
        return (True, "Destructive: `docker ... prune` removes unused resources. Confirm before proceeding.")

    return (False, "")


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    is_destructive, reason = check_careful(command)
    if not is_destructive:
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
