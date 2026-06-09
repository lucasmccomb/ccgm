#!/usr/bin/env python3
"""
CCGM /audit pack registry loader.

Input  (stdin or first positional arg): detector JSON produced by detect-ecosystems.sh
  {
    "detected_ecosystems": ["javascript", "typescript"],
    "project_shape": {
      "has_migrations": true,
      "has_dockerfile": false,
      "has_workflows": true,
      "is_extension": false,
      "is_mobile": false,
      "monorepo_packages": [],
      "frameworks": ["react"]
    },
    "available_tools": ["semgrep", "gitleaks"]
  }

Output (stdout): JSON array of applicable pack objects, each validated against
  pack.schema.json (stdlib validation — no jsonschema dep).

Exit codes:
  0  success
  1  input/schema error
"""

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal stdlib JSON Schema validator (subset used by pack.schema.json)
# Covers: type, required, additionalProperties, enum, const, pattern,
#         minItems, anyOf, $ref (local defs only), array items.
# ---------------------------------------------------------------------------

_VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_VALID_CONFIDENCES = {"high", "medium", "low"}
_VALID_DETECTIONS = {"tool", "llm", "hybrid"}
_VALID_SHAPE_FLAGS = {
    "has_migrations", "has_dockerfile", "has_workflows", "is_extension", "is_mobile"
}


class ValidationError(Exception):
    pass


def _validate_check(check: object, path: str) -> None:
    """Validate a single check object against the check $def."""
    if not isinstance(check, dict):
        raise ValidationError(f"{path}: must be an object")

    required = {"id", "severity", "confidence", "detection"}
    missing = required - check.keys()
    if missing:
        raise ValidationError(f"{path}: missing required fields: {sorted(missing)}")

    allowed = {"id", "severity", "confidence", "detection", "tool", "rule", "fallback", "auto_fixable"}
    extra = check.keys() - allowed
    if extra:
        raise ValidationError(f"{path}: unexpected fields: {sorted(extra)}")

    _id = check["id"]
    if not isinstance(_id, str) or not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_.,-]+", _id):
        raise ValidationError(f"{path}.id: must match pattern ^[a-z0-9_-]+/[a-z0-9_.-]+$ (got {_id!r})")

    if check["severity"] not in _VALID_SEVERITIES:
        raise ValidationError(f"{path}.severity: must be one of {sorted(_VALID_SEVERITIES)}")

    if check["confidence"] not in _VALID_CONFIDENCES:
        raise ValidationError(f"{path}.confidence: must be one of {sorted(_VALID_CONFIDENCES)}")

    if check["detection"] not in _VALID_DETECTIONS:
        raise ValidationError(f"{path}.detection: must be one of {sorted(_VALID_DETECTIONS)}")

    if "auto_fixable" in check and not isinstance(check["auto_fixable"], bool):
        raise ValidationError(f"{path}.auto_fixable: must be a boolean")

    for field in ("tool", "rule", "fallback"):
        if field in check and not isinstance(check[field], str):
            raise ValidationError(f"{path}.{field}: must be a string")


def _validate_applies_when_item(item: object, path: str) -> None:
    """Validate a single applies_when item."""
    if not isinstance(item, str):
        raise ValidationError(f"{path}: must be a string")

    # const "always"
    if item == "always":
        return

    # project-shape flags
    if item in _VALID_SHAPE_FLAGS:
        return

    # language predicates
    if re.fullmatch(r"language:[a-z][a-z0-9_-]*", item):
        return

    raise ValidationError(
        f"{path}: {item!r} is not a valid applies_when item. "
        f"Must be 'always', a project-shape flag {sorted(_VALID_SHAPE_FLAGS)}, "
        "or a 'language:<lang>' predicate."
    )


def validate_pack(pack: object, pack_path: str = "<unknown>") -> None:
    """
    Validate a pack manifest against the rules encoded in pack.schema.json.
    Raises ValidationError with a descriptive message on failure.
    """
    if not isinstance(pack, dict):
        raise ValidationError(f"{pack_path}: pack must be a JSON object")

    required = {"id", "name", "version", "applies_when", "checks"}
    missing = required - pack.keys()
    if missing:
        raise ValidationError(f"{pack_path}: missing required fields: {sorted(missing)}")

    allowed = {"id", "name", "version", "applies_when", "tags", "severity_floor", "tools", "checks"}
    extra = pack.keys() - allowed
    if extra:
        raise ValidationError(f"{pack_path}: unexpected fields: {sorted(extra)}")

    # id
    _id = pack["id"]
    if not isinstance(_id, str) or not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_-]+", _id):
        raise ValidationError(f"{pack_path}.id: must match pattern ^[a-z0-9_-]+/[a-z0-9_-]+$ (got {_id!r})")

    # name
    if not isinstance(pack["name"], str) or not pack["name"].strip():
        raise ValidationError(f"{pack_path}.name: must be a non-empty string")

    # version
    if not isinstance(pack["version"], str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", pack["version"]):
        raise ValidationError(f"{pack_path}.version: must be a semver string like '1.0.0'")

    # applies_when
    aw = pack["applies_when"]
    if not isinstance(aw, list) or len(aw) < 1:
        raise ValidationError(f"{pack_path}.applies_when: must be a non-empty array")
    for i, item in enumerate(aw):
        _validate_applies_when_item(item, f"{pack_path}.applies_when[{i}]")

    # tags (optional)
    if "tags" in pack:
        if not isinstance(pack["tags"], list):
            raise ValidationError(f"{pack_path}.tags: must be an array")
        for i, t in enumerate(pack["tags"]):
            if not isinstance(t, str):
                raise ValidationError(f"{pack_path}.tags[{i}]: must be a string")

    # severity_floor (optional)
    if "severity_floor" in pack:
        if pack["severity_floor"] not in _VALID_SEVERITIES:
            raise ValidationError(f"{pack_path}.severity_floor: must be one of {sorted(_VALID_SEVERITIES)}")

    # tools (optional)
    if "tools" in pack:
        if not isinstance(pack["tools"], list):
            raise ValidationError(f"{pack_path}.tools: must be an array")
        for i, t in enumerate(pack["tools"]):
            if not isinstance(t, str):
                raise ValidationError(f"{pack_path}.tools[{i}]: must be a string")

    # checks
    checks = pack["checks"]
    if not isinstance(checks, list) or len(checks) < 1:
        raise ValidationError(f"{pack_path}.checks: must be a non-empty array")
    for i, check in enumerate(checks):
        _validate_check(check, f"{pack_path}.checks[{i}]")


# ---------------------------------------------------------------------------
# Pack applicability selection
# ---------------------------------------------------------------------------

def build_truthy_conditions(detector: dict) -> set:
    """
    Build the set of truthy condition tokens from detector output.

    Rules (plan §3.3):
    - Each detected ecosystem → "language:<ecosystem>" (lowercased)
    - Each project_shape flag that is True → that flag name
    - Always include the literal "always"
    """
    conditions = {"always"}

    ecosystems = detector.get("detected_ecosystems", [])
    for eco in ecosystems:
        if isinstance(eco, str):
            conditions.add(f"language:{eco.lower()}")

    shape = detector.get("project_shape", {})
    for flag in _VALID_SHAPE_FLAGS:
        if shape.get(flag) is True:
            conditions.add(flag)

    return conditions


def is_pack_applicable(pack: dict, conditions: set) -> bool:
    """
    A pack is applicable iff EVERY item in its applies_when[] is in the
    truthy condition set.
    """
    applies_when = pack.get("applies_when", [])
    return all(item in conditions for item in applies_when)


# ---------------------------------------------------------------------------
# Pack discovery
# ---------------------------------------------------------------------------

def discover_packs(packs_dir: Path) -> list:
    """
    Discover all pack.json files under packs_dir, validate each,
    and return the list of valid pack dicts.

    Emits a warning to stderr for any pack that fails validation
    (does not abort — lets the registry proceed with valid packs).
    """
    packs = []
    if not packs_dir.is_dir():
        return packs

    for pack_file in sorted(packs_dir.rglob("pack.json")):
        try:
            with open(pack_file, "r", encoding="utf-8") as fh:
                pack = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"WARNING: {pack_file}: invalid JSON: {exc}", file=sys.stderr)
            continue

        try:
            validate_pack(pack, str(pack_file))
        except ValidationError as exc:
            print(f"WARNING: {pack_file}: validation failed: {exc}", file=sys.stderr)
            continue

        packs.append(pack)

    return packs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: list) -> int:
    # Read detector JSON from a file arg or stdin
    if len(argv) > 1:
        path = argv[1]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"ERROR: cannot read {path!r}: {exc}", file=sys.stderr)
            return 1
    else:
        raw = sys.stdin.read()

    try:
        detector = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: detector input is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(detector, dict):
        print("ERROR: detector input must be a JSON object", file=sys.stderr)
        return 1

    # Build truthy condition set
    conditions = build_truthy_conditions(detector)

    # Locate packs directory. CCGM_PACKS_DIR env var overrides the default
    # (used by tests to inject fixture packs without touching the real packs dir).
    packs_dir_env = os.environ.get("CCGM_PACKS_DIR")
    if packs_dir_env:
        packs_dir = Path(packs_dir_env)
    else:
        script_dir = Path(__file__).parent
        packs_dir = script_dir.parent / "packs"

    # Discover and validate packs
    all_packs = discover_packs(packs_dir)

    # Select applicable packs
    applicable = [p for p in all_packs if is_pack_applicable(p, conditions)]

    print(json.dumps(applicable, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
