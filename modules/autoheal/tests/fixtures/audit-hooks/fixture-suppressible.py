#!/usr/bin/env python3
"""
Fixture hook: bypass-suppressible.

Imports hook_utils, uses is_bypass_mode for short-circuit, AND uses hard_block
for always-on safety on a narrow destructive case. Used by
test-permission-audit.sh to validate classifier behavior on a known shape.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


def main() -> int:
    data = hook_utils.read_hook_input()
    cmd = data.get("tool_input", {}).get("command", "")

    if "DROP TABLE" in cmd:
        hook_utils.hard_block("Refusing DROP TABLE: bypass-proof safety.")

    if hook_utils.is_bypass_mode(data):
        return 0

    hook_utils.emit_decision("ask", "Confirm before running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
