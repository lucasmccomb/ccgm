#!/usr/bin/env python3
"""
Fixture hook: pre-migration baseline.

Does not import the shared helper module. Does not use the bypass-aware
short-circuit. Does not use the bypass-proof block helper. Represents an
unmigrated hook.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
