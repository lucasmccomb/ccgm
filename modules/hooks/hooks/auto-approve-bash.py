#!/usr/bin/env python3
"""
PreToolUse hook that enforces Bash permissions from settings.json.

Classification (plan.md §5 Epic 1): bypass-suppressible for allow/deny pattern
matching; the curated destructive set and smart-rules run OUTSIDE the bypass
short-circuit so they survive bypass mode via `hook_utils.hard_block()`.

Execution order in main():
  1. curated destructive set (always run; hard_block, bypass-proof)
  2. smart-rules (always run; destructive-reset → hard_block, bypass-proof)
  3. bypass-mode short-circuit (exit 0)
  4. settings.json allow/deny pattern matching (per-segment)

Deny/allow matching is PER SEGMENT: the command is decomposed on &&, ||, ;,
|, newlines, and command substitution before matching, so a chained command
like "echo hi && rm -rf /" cannot smuggle a denied/dangerous segment past
the list (GitHub issue #660).

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

    NOTE: This matches a SINGLE command segment. Whole-command matching is
    done by check_pattern_decision(), which first decomposes a chained
    command into segments via split_command_segments() and applies this
    matcher to each. A bare prefix match against a whole chained string
    (e.g. "echo hi && rm -rf /") would let a benign leading command smuggle
    a dangerous trailing one past the deny list — see GitHub issue #660.
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


# Shell tokens that separate one command from the next. A deny pattern must
# be evaluated against every segment, not just the head of the whole string,
# or chaining slips dangerous commands past the deny list (issue #660).
_SEGMENT_SEPARATORS = re.compile(r"&&|\|\||[;|\n]")

# Command-substitution forms: $( ... ) and `...`. Their inner command runs,
# so it must be decomposed and checked just like a top-level segment.
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def split_command_segments(command: str) -> list[str]:
    """
    Decompose a shell command string into independently-runnable segments.

    Splits on the operators that chain or pipe commands (`&&`, `||`, `;`,
    `|`, newlines) and lifts out command substitutions (`$(...)`, backticks)
    so their inner commands are evaluated too. Every returned segment is a
    candidate command that the shell would actually execute; the deny list
    must be checked against each one.

    This is a best-effort lexical split, not a full shell parser. It does not
    track quoting, so a separator inside a quoted string is still treated as a
    separator. For a SECURITY deny check that bias is correct: over-splitting
    only produces extra segments to inspect, never fewer.

    Returns a flat list of non-empty, stripped segments. Always returns at
    least one element for a non-empty command.
    """
    work = [command]
    out: list[str] = []
    while work:
        current = work.pop()
        # Lift any command substitutions into their own segments, replacing
        # the substitution text with a space so the surrounding command is
        # still inspected as its own segment.
        subs = list(_SUBSTITUTION.finditer(current))
        if subs:
            for m in subs:
                inner = m.group(1) if m.group(1) is not None else m.group(2)
                if inner and inner.strip():
                    work.append(inner)
            current = _SUBSTITUTION.sub(" ", current)
        for part in _SEGMENT_SEPARATORS.split(current):
            part = part.strip()
            if part:
                out.append(part)
    return out or ([command.strip()] if command.strip() else [])


# Curated set of destructive command shapes that must be hard-blocked even in
# bypass-permission mode. These mirror the destructive-git-reset smart-rule:
# each is checked ABOVE the bypass short-circuit and promoted to
# hook_utils.hard_block() (exit 2), the only mechanism that survives bypass
# mode (GitHub issue #39344). Patterns are deliberately narrow — they target
# whole-disk / root destruction, not ordinary cleanup like `rm -rf ./build`.
_DESTRUCTIVE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    # rm with recursive+force flags targeting the filesystem root or a
    # top-level system dir. Matches combined (-rf/-fr) and split (-r ... -f)
    # flag forms; the flag run must contain both r and f.
    (
        "recursive root delete",
        re.compile(
            r"\brm\b(?=(?:\s+-[a-zA-Z]*)*\s+-[a-zA-Z]*r[a-zA-Z]*\b)"
            r"(?=(?:\s+-[a-zA-Z]*)*\s+-[a-zA-Z]*f[a-zA-Z]*\b)"
            r".*?\s(?:/|/\*|~|\$HOME|/etc|/usr|/bin|/var|/boot|/lib|/sys|/dev)"
            r"(?:/\S*)?\s*$"
        ),
    ),
    # Filesystem creation over a block device (mkfs, mkfs.ext4, etc.).
    ("filesystem format (mkfs)", re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b")),
    # Raw disk write via dd to a device node.
    ("raw disk write (dd of=/dev)", re.compile(r"\bdd\b[^\n]*\bof=/dev/")),
    # Overwriting a partition / whole disk device directly.
    ("device overwrite", re.compile(r"\bof=/dev/(?:sd|hd|nvme|disk|mapper)\S*")),
    # Forking bomb.
    ("fork bomb", re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:")),
    # Overwriting a whole disk via shred.
    ("disk shred", re.compile(r"\bshred\b[^\n]*\s/dev/")),
]


def check_destructive(command: str) -> tuple[str | None, str | None]:
    """
    Detect curated destructive command shapes in any segment of `command`.

    Run ABOVE the bypass short-circuit in main(); a hit is promoted to
    hook_utils.hard_block() (exit 2) so it cannot be bypassed by
    --dangerously-skip-permissions. Decomposes the command first so a
    destructive segment hidden behind a benign one (e.g.
    "echo go && rm -rf /") is still caught.

    Returns (label, reason) on the first destructive segment, else (None, None).
    """
    for segment in split_command_segments(command):
        for label, regex in _DESTRUCTIVE_PATTERNS:
            if regex.search(segment):
                return (
                    label,
                    f"Refusing destructive command ({label}): {segment!r}. "
                    "This is hard-blocked even in bypass-permission mode. "
                    "If this is intentional, run it manually outside Claude Code.",
                )
    return (None, None)


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
    Allow/deny decision from settings.json patterns, evaluated PER SEGMENT.

    The command is decomposed into segments (split_command_segments) so that
    chaining cannot smuggle a denied command past the list. Rules:

      - DENY if ANY segment matches ANY deny pattern. A chain is only as safe
        as its most dangerous link.
      - ALLOW only if EVERY segment matches some allow pattern. One
        un-allowed segment means the whole chain falls through (returns None),
        so the caller's normal permission flow still applies to it.

    Smart-rules and the destructive set are NOT consulted here — main() runs
    those first so their hard_block fires bypass-proof.

    Returns: (decision, reason) where decision is "allow", "deny", or None.
    """
    segments = split_command_segments(command)

    # DENY wins: any denied segment blocks the whole command.
    for segment in segments:
        for pattern in deny_patterns:
            if pattern_matches_command(pattern, segment):
                return (
                    "deny",
                    f"Command segment {segment!r} matches deny pattern: {pattern}",
                )

    # ALLOW only when every segment is explicitly allowed.
    if allow_patterns and segments:
        all_allowed = all(
            any(pattern_matches_command(p, seg) for p in allow_patterns)
            for seg in segments
        )
        if all_allowed:
            return ("allow", "All command segments match allow patterns")

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

    # 1. Curated destructive set runs first and OUTSIDE the bypass
    #    short-circuit so whole-disk / root destruction hard-blocks even in
    #    bypass mode. Checked per-segment so chaining cannot hide it.
    destructive_label, destructive_reason = check_destructive(command)
    if destructive_label:
        hook_utils.hard_block(destructive_reason or "destructive command blocked")

    # 2. Smart-rules run next, also OUTSIDE the bypass short-circuit so the
    #    destructive-reset hard-blocks even in bypass mode.
    smart_decision, smart_reason = check_smart_rules(command)
    if smart_decision == "hard_block":
        hook_utils.hard_block(smart_reason or "destructive smart-rule matched")
    if smart_decision == "allow":
        hook_utils.emit_decision("allow", smart_reason or "smart-rule allow")
    # "deny" via smart-rule is unused now (legacy path).

    # 3. Bypass mode: skip pattern matching. The session has opted out
    #    of permission noise, and smart-rule hard-blocks have already
    #    fired for the genuinely dangerous cases.
    if hook_utils.is_bypass_mode(input_data):
        sys.exit(0)

    # 4. Pattern matching against settings.json allow/deny lists.
    allow_patterns, deny_patterns = load_settings()
    decision, reason = check_pattern_decision(command, allow_patterns, deny_patterns)

    if decision:
        hook_utils.emit_decision(decision, reason or "")

    sys.exit(0)

if __name__ == "__main__":
    main()
