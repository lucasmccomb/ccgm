#!/usr/bin/env python3
"""Stable installed entry point for pilot workflow policy."""
from pathlib import Path
from runpy import run_path

_exports = run_path(str(Path(__file__).resolve().parents[1] / 'skills/cross-agent-review/scripts/review_policy.py'))
globals().update({key: value for key, value in _exports.items() if not key.startswith('__')})
if __name__ == '__main__':
    raise SystemExit(main())
