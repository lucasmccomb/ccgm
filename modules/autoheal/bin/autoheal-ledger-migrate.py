#!/usr/bin/env python3
"""autoheal-ledger-migrate.py - move proposals/{date}.jsonl into the ledger.

One-time migration for #1099 Phase 3.1. Reads every proposals/*.jsonl and
proposals/*.jsonl.gz under the autoheal dir ($CCGM_AUTOHEAL_DIR, default
~/.claude/autoheal) and appends the rows to proposals.jsonl:

  - rows with a `signature_id` (written by the redesigned analyzer) keep their state
  - every other row (the pre-redesign proposals) becomes state "legacy" and is never shown
  - `proposed_diff_target` and `proposed_diff` are renamed to `target` and `diff`

Usage:
  autoheal-ledger-migrate.py              dry run: print the plan, change nothing
  autoheal-ledger-migrate.py --dry-run    the same, spelled out
  autoheal-ledger-migrate.py --apply      append to the ledger, then move proposals/
                                          to proposals.migrated/

Rows already in the ledger (identical content) are skipped, so a second --apply
adds nothing. Nothing runs this on install or import; run it by hand.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import importlib.util
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _ledger():
    spec = importlib.util.spec_from_file_location("autoheal_ledger", os.path.join(_HERE, "..", "lib", "ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def convert(row: dict) -> dict:
    """The ledger form of a per-day row."""
    out = dict(row)
    target = out.pop("proposed_diff_target", None)
    diff = out.pop("proposed_diff", None)
    if target is not None and "target" not in out:
        out["target"] = target
    if diff is not None and "diff" not in out:
        out["diff"] = diff
    if not isinstance(out.get("signature_id"), str):
        out["state"] = "legacy"
    else:
        out.setdefault("state", "ready")
    return out


def _canon(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan only (the default)")
    mode.add_argument("--apply", action="store_true", help="write the ledger and retire proposals/")
    args = ap.parse_args(argv)

    ledger = _ledger()
    root = ledger.autoheal_dir()
    src = os.path.join(root, "proposals")
    files = sorted(glob.glob(os.path.join(src, "*.jsonl")) + glob.glob(os.path.join(src, "*.jsonl.gz")))
    if not files:
        print(f"nothing to migrate: no proposals/*.jsonl under {root}")
        return 0

    rows = [convert(r) for path in files for r in _read(path)]
    present = {_canon(r) for r in ledger.read_rows()}
    new = [r for r in rows if _canon(r) not in present]
    states = collections.Counter(r["state"] for r in new)

    print(f"{'apply' if args.apply else 'dry run'}: {len(files)} files, {len(rows)} rows, "
          f"{len(rows) - len(new)} already in the ledger, {len(new)} to add")
    print(f"  legacy: {states.get('legacy', 0)}")
    for state, n in sorted(states.items()):
        if state != "legacy":
            print(f"  {state}: {n}")
    print(f"  ledger: {ledger.ledger_path()}")
    if not args.apply:
        print("dry run only; rerun with --apply to write the ledger")
        return 0

    for row in new:
        ledger.append_row(row)
    retired = os.path.join(root, "proposals.migrated")
    if os.path.exists(retired):
        for path in files:
            shutil.move(path, os.path.join(retired, os.path.basename(path)))
        shutil.rmtree(src, ignore_errors=True)
    else:
        os.rename(src, retired)
    print(f"wrote {len(new)} rows; moved proposals/ to {retired}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
