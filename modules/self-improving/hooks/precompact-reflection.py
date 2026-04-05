#!/usr/bin/env python3
"""
PreCompact hook that reminds the agent to capture unwritten patterns
before context is compressed.

Fires before context compaction begins. By the time PostCompact fires,
the session context is already compressed and learnings may be lost.

PreCompact input schema: TBD - verify empirically before relying on
specific fields. The hook's logic is simple (read stdin, print reminder)
so field names don't affect behavior.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    # Read stdin (required by hook contract)
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    # Always inject the reflection reminder on PreCompact
    print("<precompact-reflection>")
    print("Context compaction approaching. Before this session's context is compressed,")
    print("check if there are unwritten patterns or learnings from this session that")
    print("should be captured to memory files. Run the reflection checklist from the")
    print("self-improving rules, or invoke /reflect for a structured pass.")
    print("</precompact-reflection>")


if __name__ == "__main__":
    main()
