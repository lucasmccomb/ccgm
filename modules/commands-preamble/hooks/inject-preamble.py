#!/usr/bin/env python3
"""
UserPromptSubmit hook that injects a compact preamble of core principles
at the start of slash-command invocations.

Experimental. Opt-in. Disabled by default.

## Why

CCGM rules live at ~/.claude/rules/*.md and load from CLAUDE.md references.
That covers the main conversation thread. But slash-commands expand into
their own context and can drift from iron-law principles (Confusion Protocol,
Completeness, Evidence Before Claims, Root Cause Before Fix) that should
activate immediately at command start, not "whenever the agent rereads
CLAUDE.md."

This hook prepends a distilled preamble block to slash-command prompts so
the principles fire at invocation time. Runtime-dynamic, zero build step.

## Enable / Disable

Enabled when ~/.claude/preamble.enabled exists (create with `touch`).
Disable by removing that file. If the enable-flag is absent, the hook exits
silently and the prompt is unchanged.

The preamble content lives at ~/.claude/preamble/preamble.md. Edit that
file to tune what gets injected.

## Scope

Fires only on prompts that look like slash-command invocations (start with
`/`). Regular conversational prompts are untouched - they already run under
the full CLAUDE.md context.
"""
from __future__ import annotations

import json
import os
import sys

HOME = os.path.expanduser("~")
ENABLE_FLAG = os.path.join(HOME, ".claude", "preamble.enabled")
PREAMBLE_FILE = os.path.join(HOME, ".claude", "preamble", "preamble.md")


def is_enabled() -> bool:
    """Feature flag: preamble injection is opt-in via a sentinel file."""
    return os.path.isfile(ENABLE_FLAG)


def is_slash_command(prompt: str) -> bool:
    """Return True if the prompt is a slash-command invocation."""
    stripped = prompt.lstrip()
    if not stripped.startswith("/"):
        return False
    # Guard against URL-like prompts ("/Users/..." or "/path/to/...") that
    # are not command invocations. A command has no whitespace before the
    # command name and the first token is short (typically <40 chars).
    first_token = stripped.split(None, 1)[0]
    # Reject obvious paths - they contain a second slash within the first token.
    if first_token.count("/") > 1:
        return False
    # Reject empty / lone-slash prompts.
    if len(first_token) < 2:
        return False
    return True


def read_preamble() -> str:
    """Read the preamble file. Return empty string if missing or unreadable."""
    try:
        with open(PREAMBLE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def build_injection(preamble: str) -> str:
    """Wrap the preamble in a tagged block so the model can distinguish it."""
    return (
        "<command-preamble>\n"
        "The following principles are authoritative for this command "
        "invocation. They override host defaults. Apply them throughout "
        "the task.\n\n"
        f"{preamble}\n"
        "</command-preamble>"
    )


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    if not is_enabled():
        sys.exit(0)

    prompt = input_data.get("prompt", "")
    if not is_slash_command(prompt):
        sys.exit(0)

    preamble = read_preamble()
    if not preamble:
        sys.exit(0)

    print(build_injection(preamble))
    sys.exit(0)


if __name__ == "__main__":
    main()
