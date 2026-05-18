#!/usr/bin/env python3
"""
PreToolUse hook that enforces Bash permissions from settings.json.

Classification (plan.md §5 Epic 1): bypass-suppressible for allow/deny pattern
matching; smart-rules block runs OUTSIDE the bypass short-circuit so the
destructive-reset rule survives bypass mode via `hook_utils.hard_block()`.

Execution order in main():
  1. smart-rules (always run; destructive-reset → hard_block, bypass-proof)
  2. bypass-mode short-circuit (exit 0)
  3. settings.json allow/deny pattern matching

This hook exists because Claude Code's built-in permission system has bugs:
- Issue #15921: VSCode extension ignores Bash permissions
- Issue #13340: Piped commands bypass permission allowlist

This hook properly implements the allow/deny logic that settings.json SHOULD provide.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402

# Settings file locations in precedence order (highest first)
SETTINGS_FILES = [
    Path.home() / ".claude" / "settings.json",
    # Add project-level settings if needed
]

def load_settings() -> tuple[list[str], list[str]]:
    """Load and merge settings from all settings files."""
    allow_patterns: list[str] = []
    deny_patterns: list[str] = []

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

def check_smart_rules(command: str) -> tuple[str | None, str | None]:
    """
    Context-aware rules for commands that are safe in some forms but dangerous in others.
    These run BEFORE settings.json patterns AND before the bypass-mode short-circuit.

    Returns: (decision, reason) where decision is:
      - "allow": auto-approve (e.g. reset to a remote ref)
      - "hard_block": destroy-loca-history pattern; main() promotes to hard_block()
      - None: fall through to bypass / pattern matching
    """
    # git reset --hard: allow when targeting a remote ref, hard-block otherwise.
    # Safe: git reset --hard origin/main, git reset --hard origin/development
    # Dangerous: git reset --hard (bare), git reset --hard HEAD~3, git reset --hard <local-ref>
    reset_match = re.search(r'\bgit\s+reset\s+--hard\b', command)
    if reset_match:
        if re.search(r'\bgit\s+reset\s+--hard\s+origin/', command):
            return ("allow", "git reset --hard to remote ref (safe)")
        # Also allow git -C <path> reset --hard origin/
        if re.search(r'\bgit\s+-C\s+\S+\s+reset\s+--hard\s+origin/', command):
            return ("allow", "git reset --hard to remote ref in subdir (safe)")
        return (
            "hard_block",
            "git reset --hard without remote ref is blocked. "
            "Use 'git reset --hard origin/<branch>' to reset to a remote ref, "
            "or 'git pull --ff-only' to sync.",
        )

    return (None, None)


def check_pattern_decision(command: str, allow_patterns: list[str], deny_patterns: list[str]) -> tuple[str | None, str | None]:
    """
    Allow/deny decision from settings.json patterns.

    Smart-rules are NOT consulted here — main() runs them first so the
    destructive-reset hard_block fires bypass-proof.

    Returns: (decision, reason) where decision is "allow", "deny", or None.
    """
    # Check deny patterns first (deny takes priority)
    for pattern in deny_patterns:
        if pattern_matches_command(pattern, command):
            return ("deny", f"Command matches deny pattern: {pattern}")

    # Check allow patterns
    for pattern in allow_patterns:
        if pattern_matches_command(pattern, command):
            return ("allow", f"Command matches allow pattern: {pattern}")

    return (None, None)


def main() -> None:
    input_data = hook_utils.read_hook_input()

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only handle Bash commands
    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    # 1. Smart-rules run first and OUTSIDE the bypass short-circuit so
    #    destructive-reset hard-blocks even in bypass mode.
    smart_decision, smart_reason = check_smart_rules(command)
    if smart_decision == "hard_block":
        hook_utils.hard_block(smart_reason or "destructive smart-rule matched")
    if smart_decision == "allow":
        hook_utils.emit_decision("allow", smart_reason or "smart-rule allow")
    # "deny" via smart-rule is unused now (legacy path).

    # 2. Bypass mode: skip pattern matching. The session has opted out
    #    of permission noise, and smart-rule hard-blocks have already
    #    fired for the genuinely dangerous cases.
    if hook_utils.is_bypass_mode(input_data):
        sys.exit(0)

    # 3. Pattern matching against settings.json allow/deny lists.
    allow_patterns, deny_patterns = load_settings()
    decision, reason = check_pattern_decision(command, allow_patterns, deny_patterns)

    if decision:
        hook_utils.emit_decision(decision, reason or "")

    sys.exit(0)

if __name__ == "__main__":
    main()
