#!/usr/bin/env python3
"""Stable installed CLI/import entry point for the self-contained review skill."""
from pathlib import Path
from runpy import run_path

_runtime = Path(__file__).resolve().parents[1] / 'skills/cross-agent-review/scripts/cross_agent_review.py'
_exports = run_path(str(_runtime))
globals().update({key: value for key, value in _exports.items() if not key.startswith('__')})

if __name__ == '__main__':
    raise SystemExit(main())
