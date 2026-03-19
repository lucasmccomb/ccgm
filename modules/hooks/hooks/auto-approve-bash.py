#!/usr/bin/env python3
"""
PreToolUse hook that enforces Bash permissions from settings.json.

This hook exists because Claude Code's built-in permission system has bugs:
- Issue #15921: VSCode extension ignores Bash permissions
- Issue #13340: Piped commands bypass permission allowlist

This hook properly implements the allow/deny logic that settings.json SHOULD provide.
"""
import json
import sys
import os
import re
from pathlib import Path

# Settings file locations in precedence order (highest first)
SETTINGS_FILES = [
    Path.home() / ".claude" / "settings.json",
    # Add project-level settings if needed
]

def load_settings():
    """Load and merge settings from all settings files."""
    allow_patterns = []
    deny_patterns = []

    for settings_file in SETTINGS_FILES:
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                    permissions = settings.get("permissions", {})

                    # Extract Bash patterns from allow list
                    for rule in permissions.get("allow", []):
                        if rule.startswith("Bash(") and rule.endswith(")"):
                            pattern = rule[5:-1]  # Extract pattern from Bash(...)
                            allow_patterns.append(pattern)

                    # Extract Bash patterns from deny list
                    for rule in permissions.get("deny", []):
                        if rule.startswith("Bash(") and rule.endswith(")"):
                            pattern = rule[5:-1]  # Extract pattern from Bash(...)
                            deny_patterns.append(pattern)
            except (json.JSONDecodeError, IOError):
                continue

    return allow_patterns, deny_patterns

def pattern_matches_command(pattern: str, command: str) -> bool:
    """
    Check if a permission pattern matches a command.

    Patterns use prefix matching with :* as wildcard suffix.
    Examples:
        - "mkdir:*" matches "mkdir -p /foo/bar"
        - "git status:*" matches "git status"
        - "npm run lint" matches exactly "npm run lint" or "npm run lint ..."
    """
    command = command.strip()

    # Handle :* wildcard suffix (matches anything after the prefix)
    if pattern.endswith(":*"):
        prefix = pattern[:-2]  # Remove :*
        return command.startswith(prefix)

    # Handle patterns with space before * (e.g., "mkdir *")
    if pattern.endswith(" *"):
        prefix = pattern[:-2]  # Remove " *"
        return command.startswith(prefix)

    # Exact match or prefix match
    return command.startswith(pattern)

def check_command(command: str, allow_patterns: list, deny_patterns: list) -> tuple:
    """
    Check if a command should be allowed or denied.

    Returns: (decision, reason)
        decision: "allow", "deny", or None (let default system handle)
    """
    # Check deny patterns first (deny takes priority)
    for pattern in deny_patterns:
        if pattern_matches_command(pattern, command):
            return ("deny", f"Command matches deny pattern: {pattern}")

    # Check allow patterns
    for pattern in allow_patterns:
        if pattern_matches_command(pattern, command):
            return ("allow", f"Command matches allow pattern: {pattern}")

    # No match - let the default permission system handle it
    # Return None to not output anything and exit 0
    return (None, None)

def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # Non-blocking exit on invalid input

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only handle Bash commands
    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    # Load patterns from settings
    allow_patterns, deny_patterns = load_settings()

    # Check the command
    decision, reason = check_command(command, allow_patterns, deny_patterns)

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

if __name__ == "__main__":
    main()
