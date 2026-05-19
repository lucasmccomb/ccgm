#!/usr/bin/env python3
"""
Fixture hook: always-on safety.

Imports the shared helper module and uses a bypass-proof block helper as
always-on safety. Does NOT call the bypass-aware short-circuit helper
(intentionally — this hook is data-integrity enforcement that must run even
when the user is in bypass mode).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


def main() -> int:
    data = hook_utils.read_hook_input()
    cmd = data.get("tool_input", {}).get("command", "")

    if cmd.startswith("rm -rf /"):
        hook_utils.hard_block("Refusing rm -rf against root path.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
