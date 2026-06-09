#!/usr/bin/env python3
"""
lint-rubric.py — Validates schemas/severity-rubric.json structure and enums.

Checks:
  1. The file parses as valid JSON.
  2. Every entry under "checks" has exactly the required keys.
  3. All enum values are within the allowed sets.
  4. Orphan check-id gate: every check-id found in packs/**/pack.json has a rubric entry.

Exit codes:
  0 — all checks pass
  1 — validation failures found (details printed to stderr)

Usage:
  python3 lint-rubric.py [--rubric PATH] [--packs-dir PATH]

Defaults (relative to this script's parent directory, i.e. the audit skill root):
  --rubric    schemas/severity-rubric.json
  --packs-dir packs
"""

import argparse
import json
import sys
from pathlib import Path

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
VALID_CONFIDENCES = {"high", "medium", "low"}
REQUIRED_KEYS = {"severity", "confidence", "fix_confidence"}

# check_id must match the pattern from finding.schema.json: ^[a-z0-9_-]+/[a-z0-9_.-]+$
import re
CHECK_ID_RE = re.compile(r'^[a-z0-9_-]+/[a-z0-9_.-]+$')


def load_rubric(rubric_path: Path) -> dict:
    try:
        with open(rubric_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: rubric file not found: {rubric_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: rubric file is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    return data


def validate_rubric(data: dict) -> list[str]:
    errors = []

    if not isinstance(data, dict):
        return ["rubric root must be a JSON object"]

    checks = data.get("checks")
    if checks is None:
        return ['rubric missing top-level "checks" key']
    if not isinstance(checks, dict):
        return ['"checks" must be a JSON object']

    for check_id, entry in checks.items():
        prefix = f"checks[{check_id!r}]"

        # Validate check_id format
        if not CHECK_ID_RE.match(check_id):
            errors.append(
                f"{prefix}: check_id does not match pattern ^[a-z0-9_-]+/[a-z0-9_.-]+$"
            )

        if not isinstance(entry, dict):
            errors.append(f"{prefix}: entry must be a JSON object, got {type(entry).__name__}")
            continue

        # Check required keys present
        missing = REQUIRED_KEYS - entry.keys()
        if missing:
            errors.append(f"{prefix}: missing required keys: {sorted(missing)}")

        extra = set(entry.keys()) - REQUIRED_KEYS
        if extra:
            errors.append(f"{prefix}: unexpected keys: {sorted(extra)}")

        # Validate enum values
        severity = entry.get("severity")
        if severity is not None and severity not in VALID_SEVERITIES:
            errors.append(
                f"{prefix}: severity={severity!r} not in {sorted(VALID_SEVERITIES)}"
            )

        confidence = entry.get("confidence")
        if confidence is not None and confidence not in VALID_CONFIDENCES:
            errors.append(
                f"{prefix}: confidence={confidence!r} not in {sorted(VALID_CONFIDENCES)}"
            )

        fix_confidence = entry.get("fix_confidence")
        if fix_confidence is not None and fix_confidence not in VALID_CONFIDENCES:
            errors.append(
                f"{prefix}: fix_confidence={fix_confidence!r} not in {sorted(VALID_CONFIDENCES)}"
            )

    return errors


def collect_pack_check_ids(packs_dir: Path) -> list[tuple[str, str]]:
    """Return list of (check_id, source_path) for every check in packs/**/pack.json.

    The orphan-check-id gate: every check-id shipped in a pack must have a rubric entry.
    With zero packs this returns an empty list and the gate passes trivially.
    Becomes meaningful as pack epics land.
    """
    results = []
    for pack_file in sorted(packs_dir.rglob("pack.json")):
        try:
            with open(pack_file) as f:
                pack = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: could not read {pack_file}: {e}", file=sys.stderr)
            continue

        checks = pack.get("checks", [])
        if not isinstance(checks, list):
            continue
        for check in checks:
            if isinstance(check, dict):
                cid = check.get("check_id") or check.get("id")
            else:
                cid = str(check)
            if cid:
                results.append((cid, str(pack_file)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate severity-rubric.json")
    parser.add_argument(
        "--rubric",
        default=None,
        help="Path to severity-rubric.json (default: <script_dir>/../schemas/severity-rubric.json)",
    )
    parser.add_argument(
        "--packs-dir",
        default=None,
        help="Path to packs/ directory (default: <script_dir>/../packs)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    skill_root = script_dir.parent

    rubric_path = Path(args.rubric) if args.rubric else skill_root / "schemas" / "severity-rubric.json"
    packs_dir = Path(args.packs_dir) if args.packs_dir else skill_root / "packs"

    data = load_rubric(rubric_path)
    errors = validate_rubric(data)

    rubric_ids = set(data.get("checks", {}).keys())

    # Orphan check-id gate
    pack_entries = collect_pack_check_ids(packs_dir)
    orphan_errors = []
    for check_id, source in pack_entries:
        if check_id not in rubric_ids:
            orphan_errors.append(
                f"ORPHAN check_id {check_id!r} (from {source}) has no rubric entry"
            )

    all_errors = errors + orphan_errors

    if not all_errors:
        check_count = len(rubric_ids)
        pack_count = len(pack_entries)
        print(
            f"OK: {check_count} rubric entries valid; "
            f"{pack_count} pack check-id(s) verified against rubric"
        )
        return 0

    for err in all_errors:
        print(f"ERROR: {err}", file=sys.stderr)
    print(
        f"\n{len(all_errors)} error(s) found in {rubric_path}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
