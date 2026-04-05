#!/usr/bin/env python3
"""
PreToolUse hook that auto-approves Read, Edit, and Write operations for allowed paths.

This hook exists because Claude Code's built-in permission system has bugs:
- Issue #15921: VSCode extension ignores Edit/Write permissions
- The permission patterns in settings.json are ignored

This hook enforces path-based permissions for file operations.
"""
from __future__ import annotations

import json
import os
import sys
from fnmatch import fnmatch
from pathlib import Path

# Settings file location
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

def load_path_patterns() -> tuple[list[str], list[str], list[str]]:
    """Load Read/Edit/Write path patterns from settings."""
    read_patterns: list[str] = []
    edit_patterns: list[str] = []
    write_patterns: list[str] = []

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                permissions = settings.get("permissions", {})

                for rule in permissions.get("allow", []):
                    if rule.startswith("Read(") and rule.endswith(")"):
                        pattern = rule[5:-1]  # Extract path from Read(...)
                        read_patterns.append(pattern)
                    elif rule.startswith("Edit(") and rule.endswith(")"):
                        pattern = rule[5:-1]  # Extract path from Edit(...)
                        edit_patterns.append(pattern)
                    elif rule.startswith("Write(") and rule.endswith(")"):
                        pattern = rule[6:-1]  # Extract path from Write(...)
                        write_patterns.append(pattern)
        except (json.JSONDecodeError, IOError):
            pass

    return read_patterns, edit_patterns, write_patterns

def path_matches_pattern(file_path: str, pattern: str) -> bool:
    """
    Check if a file path matches a glob pattern.

    Patterns use glob syntax:
        - "$HOME/code/**" matches anything under $HOME/code/
        - "/tmp/**" matches anything under /tmp/
    """
    # Normalize paths
    file_path = os.path.normpath(file_path)

    # Handle ** glob pattern (match any depth)
    if "**" in pattern:
        # Convert $HOME/code/** to $HOME/code/ prefix match
        base_path = pattern.replace("**", "").rstrip("/")
        return file_path.startswith(base_path)

    # Standard glob matching
    return fnmatch(file_path, pattern)

def check_file_path(file_path: str, patterns: list[str]) -> tuple[str | None, str | None]:
    """
    Check if a file path matches any allowed pattern.

    Returns: (decision, reason)
        decision: "allow" or None (let default system handle)
    """
    for pattern in patterns:
        if path_matches_pattern(file_path, pattern):
            return ("allow", f"Path matches allowed pattern: {pattern}")

    # No match - let the default permission system handle it
    return (None, None)

def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # Non-blocking exit on invalid input

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Load patterns from settings
    read_patterns, edit_patterns, write_patterns = load_path_patterns()

    # Handle Read tool
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            decision, reason = check_file_path(file_path, read_patterns)
            if decision:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": reason
                    }
                }
                print(json.dumps(output))
        sys.exit(0)

    # Handle Edit tool
    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        if file_path:
            decision, reason = check_file_path(file_path, edit_patterns)
            if decision:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": reason
                    }
                }
                print(json.dumps(output))
        sys.exit(0)

    # Handle Write tool
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if file_path:
            decision, reason = check_file_path(file_path, write_patterns)
            if decision:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": reason
                    }
                }
                print(json.dumps(output))
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
