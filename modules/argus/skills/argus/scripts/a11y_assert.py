#!/usr/bin/env python3
"""Deterministic accessibility-id gate for Argus.

Compares the ids the spec's a11y_contract requires for a target against the ids actually
present in the probe (the adapter's structured render dump: an accessibility tree on iOS,
a DOM/ARIA snapshot on web). Emits the a11y_ids object that goes into gate-result.json.

Generic across platforms: it recursively harvests id-like values from the probe JSON
regardless of shape, so any adapter that emits JSON works. A contract entry ending in
'*' matches a prefix family (e.g. 'row.item.*' matches 'row.item.42').

Usage:
  a11y_assert.py --probe probe.json (--spec spec.json --target list | --contract-file ids.json | --contract '["a","b.*"]') [--json]
Exit code: 0 if nothing missing, 1 if any required id is missing, 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import sys

# Keys whose string values are treated as element ids. Adapters document which they use;
# we harvest all of them so the gate is adapter-agnostic.
ID_KEYS = {
    "id",
    "identifier",
    "accessibilityIdentifier",
    "testId",
    "testid",
    "data-testid",
    "dataTestid",
}


def _err(msg: str) -> None:
    print(f"a11y_assert: {msg}", file=sys.stderr)


def harvest_ids(node, acc: set) -> None:
    """Recursively collect id-like string values from arbitrary JSON."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in ID_KEYS and isinstance(val, str) and val:
                acc.add(val)
            else:
                harvest_ids(val, acc)
    elif isinstance(node, list):
        for item in node:
            harvest_ids(item, acc)


def matches(contract_id: str, present: set) -> bool:
    if contract_id.endswith("*"):
        prefix = contract_id[:-1]
        return any(pid.startswith(prefix) for pid in present)
    return contract_id in present


def load_contract(args) -> list:
    if args.contract:
        return json.loads(args.contract)
    if args.contract_file:
        with open(args.contract_file) as f:
            return json.load(f)
    if args.spec and args.target:
        with open(args.spec) as f:
            spec = json.load(f)
        for tgt in spec.get("targets", []):
            if tgt.get("id") == args.target:
                return tgt.get("a11y_contract", [])
        raise ValueError(f"target '{args.target}' not in spec")
    raise ValueError("provide --contract, --contract-file, or --spec + --target")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Assert the probe exposes the spec's a11y ids.")
    ap.add_argument("--probe", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--target")
    ap.add_argument("--contract-file", dest="contract_file")
    ap.add_argument("--contract")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        with open(args.probe) as f:
            probe = json.load(f)
        contract = load_contract(args)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        _err(str(e))
        return 2

    present: set = set()
    harvest_ids(probe, present)
    missing = [cid for cid in contract if not matches(cid, present)]

    result = {"expected": len(contract), "present": len(contract) - len(missing), "missing": missing}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"a11y_ids: {result['present']}/{result['expected']} present", end="")
        print(f"  missing: {missing}" if missing else "  (all present)")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
