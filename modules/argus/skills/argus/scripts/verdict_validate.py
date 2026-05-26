#!/usr/bin/env python3
"""Validate + normalize an Argus judge verdict (or a gate-result) — stdlib only.

The judge's `all_pass` and `failed_dimensions` are a *claim*. Given the rubric thresholds,
whether the verdict passes is deterministic arithmetic over the per-dimension scores, so this
script recomputes it and overwrites the judge's self-report. If the judge's claim disagreed,
it says so on stderr (a signal worth logging) but still emits the corrected verdict. This is
the verification discipline applied to the judge: trust the scores, derive the verdict.

Usage:
  verdict_validate.py --kind verdict FILE --rubric rubric.json   # prints normalized verdict
  verdict_validate.py --kind gate FILE                            # prints normalized gate-result
Exit: 0 valid, 1 self-report disagreed (still emits corrected), 2 structurally invalid.
"""
from __future__ import annotations

import argparse
import json
import sys

VALID_SCORES = {0, 0.5, 1}
VALID_ANCHORS = {"reference", "design-system", "spec-text"}
PASSFAIL = {"pass", "fail", "skip"}


def _err(msg: str) -> None:
    print(f"verdict_validate: {msg}", file=sys.stderr)


def validate_verdict(v: dict, rubric: dict | None):
    for key in ("iteration", "feature", "target", "dimensions"):
        if key not in v:
            raise ValueError(f"missing required key '{key}'")
    dims = v["dimensions"]
    if not isinstance(dims, dict) or not dims:
        raise ValueError("'dimensions' must be a non-empty object")

    thresholds = {}
    if rubric:
        for name, info in rubric.get("dimensions", {}).items():
            thresholds[name] = info.get("threshold", 1)

    failed = []
    for name, info in dims.items():
        if not isinstance(info, dict):
            raise ValueError(f"dimension '{name}' must be an object")
        if info.get("score") not in VALID_SCORES:
            raise ValueError(f"dimension '{name}' score must be one of {sorted(VALID_SCORES)}")
        if info.get("anchor") not in VALID_ANCHORS:
            raise ValueError(f"dimension '{name}' anchor must be one of {sorted(VALID_ANCHORS)}")
        if not isinstance(info.get("evidence", ""), str):
            raise ValueError(f"dimension '{name}' evidence must be a string")
        threshold = thresholds.get(name, 1)
        if info["score"] < threshold:
            failed.append(name)

    derived_all_pass = len(failed) == 0
    disagreed = False
    if "all_pass" in v and v["all_pass"] != derived_all_pass:
        disagreed = True
        _err(f"judge reported all_pass={v['all_pass']} but scores derive {derived_all_pass}; correcting")
    if "failed_dimensions" in v and set(v["failed_dimensions"]) != set(failed):
        disagreed = True
        _err(f"judge reported failed={v.get('failed_dimensions')} but scores derive {failed}; correcting")

    v["all_pass"] = derived_all_pass
    v["failed_dimensions"] = failed
    return v, disagreed


def validate_gate(g: dict):
    for key in ("feature", "target", "gates"):
        if key not in g:
            raise ValueError(f"missing required key '{key}'")
    gates = g["gates"]
    if not isinstance(gates, dict):
        raise ValueError("'gates' must be an object")

    all_green = True
    for name, val in gates.items():
        if name == "a11y_ids":
            if not isinstance(val, dict) or "missing" not in val:
                raise ValueError("a11y_ids must be an object with a 'missing' array")
            if val.get("missing"):
                all_green = False
            continue
        if name == "snapshot":
            if val not in {"pass", "diff", "skip"}:
                raise ValueError(f"snapshot must be pass|diff|skip, got '{val}'")
            if val == "diff":
                all_green = False
            continue
        if val not in PASSFAIL:
            raise ValueError(f"gate '{name}' must be pass|fail|skip, got '{val}'")
        if val == "fail":
            all_green = False

    disagreed = "all_green" in g and g["all_green"] != all_green
    if disagreed:
        _err(f"gate-result reported all_green={g['all_green']} but gates derive {all_green}; correcting")
    g["all_green"] = all_green
    return g, disagreed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate + normalize an Argus verdict or gate-result.")
    ap.add_argument("--kind", required=True, choices=["verdict", "gate"])
    ap.add_argument("file")
    ap.add_argument("--rubric")
    args = ap.parse_args(argv)

    try:
        with open(args.file) as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _err(f"cannot read input: {e}")
        return 2

    rubric = None
    if args.rubric:
        try:
            with open(args.rubric) as f:
                rubric = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _err(f"cannot read rubric: {e}")
            return 2

    try:
        if args.kind == "verdict":
            normalized, disagreed = validate_verdict(doc, rubric)
        else:
            normalized, disagreed = validate_gate(doc)
    except ValueError as e:
        _err(str(e))
        return 2

    print(json.dumps(normalized, indent=2))
    return 1 if disagreed else 0


if __name__ == "__main__":
    raise SystemExit(main())
