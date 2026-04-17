#!/usr/bin/env python3
"""
PreToolUse hook that scope-locks Edit/Write to a frozen directory.

When a freeze is active (state file `~/.claude/freeze-dir.txt` exists and
contains a directory path), Edit and Write operations outside that directory
are denied. Use `/freeze <dir>` to set the scope and `/unfreeze` to clear it.

Paths are normalised (symlinks resolved, `..` collapsed) before the
containment check so trivial escape attempts (`../foo`, symlinked parent) are
caught POSIX-portably.

Ported to Python from gstack `freeze/bin/check-freeze.sh` to match CCGM's
hook style (JSON stdin/stdout, consistent with auto-approve-file-ops.py).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FREEZE_FILE = Path.home() / ".claude" / "freeze-dir.txt"


def read_freeze_dir() -> str | None:
    """Return the current freeze directory (absolute, resolved) or None."""
    if not FREEZE_FILE.exists():
        return None
    try:
        raw = FREEZE_FILE.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    # Expand ~ and environment variables, then resolve.
    expanded = os.path.expandvars(os.path.expanduser(raw))
    try:
        return str(Path(expanded).resolve())
    except OSError:
        return None


def resolve_path(path: str) -> str | None:
    """
    Resolve `path` to an absolute canonical form.

    Uses Path.resolve(strict=False) so new files (Write) that do not yet
    exist on disk still get their parent hierarchy resolved and `..` collapsed.
    """
    if not path:
        return None
    expanded = os.path.expandvars(os.path.expanduser(path))
    try:
        return str(Path(expanded).resolve())
    except OSError:
        return None


def is_within(target: str, parent: str) -> bool:
    """Return True if `target` is the same path as or nested under `parent`."""
    # Ensure trailing slash semantics so "/a/b" does not match "/a/bcd".
    parent_norm = parent.rstrip(os.sep)
    target_norm = target.rstrip(os.sep)
    if target_norm == parent_norm:
        return True
    return target_norm.startswith(parent_norm + os.sep)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    freeze_dir = read_freeze_dir()
    if not freeze_dir:
        # No freeze active. Fall through to default permission handling.
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    resolved = resolve_path(file_path)
    if resolved is None:
        # Could not resolve; fall through rather than block on malformed input.
        sys.exit(0)

    if is_within(resolved, freeze_dir):
        # In scope - let other hooks / default system decide.
        sys.exit(0)

    reason = (
        f"Freeze active: writes are scoped to {freeze_dir}. "
        f"{resolved} is outside the frozen directory. "
        f"Run `/unfreeze` to clear the scope, or stay within the frozen path."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
