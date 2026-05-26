#!/usr/bin/env python3
"""Validate an Argus feature spec (spec.json) — stdlib only.

Checks the contract against the shape in references/spec.schema.json (hand-rolled, no
jsonschema dependency) and verifies that every reference marked `present` actually exists
on disk. Reference entries marked `needed` are the human worklist (HE-1), not lint errors;
`candidate` entries are agent renders awaiting approval. Lint fails ONLY on a structural
violation or a `present` reference whose file is missing.

Usage:
  spec_lint.py path/to/spec.json [--spec-dir DIR] [--json]
Exit: 0 valid, 1 invalid (structural error or missing present-reference), 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REF_STATUS = {"present", "needed", "candidate"}


def _err(msg: str) -> None:
    print(f"spec_lint: {msg}", file=sys.stderr)


def check(cond: bool, msg: str, errors: list) -> None:
    if not cond:
        errors.append(msg)


def lint(spec: dict, spec_dir: str):
    errors: list = []
    worklist: list = []  # references that still need a human (status needed/candidate)

    check(isinstance(spec.get("feature"), str) and SLUG.match(spec.get("feature", "")),
          "feature must be a lowercase slug", errors)
    check(isinstance(spec.get("adapter"), str) and spec.get("adapter"),
          "adapter must be a non-empty string", errors)

    ds = spec.get("design_system")
    check(isinstance(ds, dict) and isinstance(ds.get("tokens"), str),
          "design_system.tokens must be a path string", errors)

    targets = spec.get("targets")
    check(isinstance(targets, list) and len(targets) >= 1, "targets must be a non-empty array", errors)
    if not isinstance(targets, list):
        return errors, worklist

    seen_ids = set()
    for i, tgt in enumerate(targets):
        loc = f"targets[{i}]"
        if not isinstance(tgt, dict):
            errors.append(f"{loc} must be an object")
            continue
        tid = tgt.get("id")
        check(isinstance(tid, str) and SLUG.match(tid or ""), f"{loc}.id must be a lowercase slug", errors)
        check(tid not in seen_ids, f"{loc}.id '{tid}' is duplicated", errors)
        seen_ids.add(tid)
        check(isinstance(tgt.get("route"), str) and tgt.get("route"), f"{loc}.route must be a non-empty string", errors)
        states = tgt.get("states")
        check(isinstance(states, list) and len(states) >= 1 and all(isinstance(s, str) for s in states),
              f"{loc}.states must be a non-empty array of strings", errors)

        for opt, typ in (("appearances", list), ("a11y_contract", list), ("references", list),
                         ("component_contracts", list), ("fixtures", dict), ("canonical", dict)):
            if opt in tgt and not isinstance(tgt[opt], typ):
                errors.append(f"{loc}.{opt} must be a {typ.__name__}")

        for j, ref in enumerate(tgt.get("references", []) or []):
            rloc = f"{loc}.references[{j}]"
            if not isinstance(ref, dict):
                errors.append(f"{rloc} must be an object")
                continue
            for rk in ("state", "appearance", "status"):
                check(rk in ref, f"{rloc} missing '{rk}'", errors)
            status = ref.get("status")
            check(status in REF_STATUS, f"{rloc}.status must be one of {sorted(REF_STATUS)}", errors)
            fpath = ref.get("file")
            if status == "present":
                check(isinstance(fpath, str) and fpath, f"{rloc} is 'present' but has no file", errors)
                if isinstance(fpath, str) and fpath:
                    abspath = fpath if os.path.isabs(fpath) else os.path.join(spec_dir, fpath)
                    check(os.path.isfile(abspath), f"{rloc} marked present but file not found: {fpath}", errors)
            elif status in ("needed", "candidate"):
                worklist.append({"target": tid, "state": ref.get("state"),
                                 "appearance": ref.get("appearance"), "status": status})

    return errors, worklist


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lint an Argus spec.json.")
    ap.add_argument("spec")
    ap.add_argument("--spec-dir", help="Base dir for resolving reference files (default: spec's dir).")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        with open(args.spec) as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _err(f"cannot read spec: {e}")
        return 2

    spec_dir = args.spec_dir or os.path.dirname(os.path.abspath(args.spec))
    errors, worklist = lint(spec, spec_dir)

    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors, "reference_worklist": worklist}, indent=2))
    else:
        for e in errors:
            print(f"  ERROR: {e}")
        for w in worklist:
            print(f"  NEEDS REFERENCE ({w['status']}): {w['target']} {w['state']}/{w['appearance']}")
        print(f"spec_lint: {'VALID' if not errors else 'INVALID'}"
              f" ({len(errors)} error(s), {len(worklist)} reference(s) awaiting a human)")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
