#!/usr/bin/env python3
"""
CCGM /audit findings JSONL emitter (Epic 1.6).

Gate decision #30: emits line-delimited JSON (one finding per line), NOT SARIF.

Input (stdin OR first positional arg): JSON array of raw finding objects.

Each raw finding MUST include at minimum:
  check_id    str   "pack/check"
  rule_id     str
  severity    str   critical|high|medium|low|info
  confidence  str   high|medium|low
  detection   str   tool|llm|hybrid
  source      str   tool|llm
  message     str
  location    obj   { path: str, line: int }

Optional on raw input:
  fingerprint   str   If present, kept VERBATIM (source-tool fingerprint)
  end_line      int   Forwarded to location if present
  fix_confidence str
  suppression   obj
  properties    obj

Output: .audit/current/findings.jsonl
  One JSON object per line, each conforming to finding.schema.json.
  Writes to the output file; directory is created if absent.

Fingerprint algorithm (section 3.7, when no source fingerprint is present):
  context = strip_all_whitespace(lower(primary_line +/- 2 lines))
  fingerprint = sha256(context.encode())[:16] + ":1"

  Primary line +/- 2 lines means lines [line-2, line+2] inclusive (1-based),
  clamped to the actual file length. If the file is missing or unreadable,
  fingerprint is computed from just the normalized message + location string
  so the caller always gets a stable, non-empty value.

  strip_all_whitespace removes ALL whitespace characters (spaces, tabs,
  newlines) before hashing, so reformatting the primary line does not change
  the fingerprint.

Exit codes:
  0  success
  1  input / validation error
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_VALID_CONFIDENCES = {"high", "medium", "low"}
_VALID_DETECTIONS = {"tool", "llm", "hybrid"}
_VALID_SOURCES = {"tool", "llm"}
_FINGERPRINT_GEN = ":1"

# Compiled patterns matching finding.schema.json
_RE_CHECK_ID = re.compile(r"^[a-z0-9_-]+/[a-z0-9_.-]+$")
_RE_FINGERPRINT = re.compile(r"^[A-Za-z0-9_.:+/=-]{8,128}$")


# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------


def _strip_all_whitespace(text: str) -> str:
    """Remove every whitespace character (spaces, tabs, newlines)."""
    return "".join(text.split())


def _read_context_lines(path: str, line: int) -> str:
    """
    Read lines [line-2, line+2] (1-based) from path, concatenated.
    Returns an empty string if the file cannot be read.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
    except OSError:
        return ""

    total = len(all_lines)
    if total == 0:
        return ""

    # line is 1-based; convert to 0-based index for slicing
    start = max(0, line - 3)    # index of line-2
    end = min(total, line + 2)  # exclusive upper bound (line+2 inclusive)
    return "".join(all_lines[start:end])


def compute_fingerprint(path: str, line: int, message: str) -> str:
    """
    Compute a stable fingerprint per section 3.7.
    Falls back to message+location if the file is missing or unreadable.
    """
    raw_context = _read_context_lines(path, line)
    if raw_context:
        normalized = _strip_all_whitespace(raw_context.lower())
    else:
        # Graceful fallback: hash message+location so the value is still stable
        fallback = f"{path}:{line}:{message}"
        normalized = _strip_all_whitespace(fallback.lower())

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:16] + _FINGERPRINT_GEN


# ---------------------------------------------------------------------------
# Schema-level validation helpers
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    pass


def _check_enum(value: object, allowed: set, field: str) -> None:
    if value not in allowed:
        raise ValidationError(
            f"{field}: '{value}' not in {sorted(allowed)}"
        )


def validate_finding(obj: dict) -> None:
    """Validate a coerced finding against finding.schema.json constraints."""
    required = {
        "check_id", "rule_id", "severity", "confidence",
        "location", "message", "fingerprint", "detection", "source",
    }
    missing = required - obj.keys()
    if missing:
        raise ValidationError(f"missing required fields: {sorted(missing)}")

    _check_enum(obj["severity"], _VALID_SEVERITIES, "severity")
    _check_enum(obj["confidence"], _VALID_CONFIDENCES, "confidence")
    _check_enum(obj["detection"], _VALID_DETECTIONS, "detection")
    _check_enum(obj["source"], _VALID_SOURCES, "source")

    if "fix_confidence" in obj:
        _check_enum(obj["fix_confidence"], _VALID_CONFIDENCES, "fix_confidence")

    loc = obj["location"]
    if not isinstance(loc, dict):
        raise ValidationError("location must be an object")
    if "path" not in loc or "line" not in loc:
        raise ValidationError("location requires 'path' and 'line'")
    if not isinstance(loc["line"], int) or loc["line"] < 1:
        raise ValidationError("location.line must be an integer >= 1")
    if "end_line" in loc:
        if not isinstance(loc["end_line"], int) or loc["end_line"] < loc["line"]:
            raise ValidationError(
                "location.end_line must be integer >= location.line"
            )

    if not _RE_CHECK_ID.match(obj["check_id"]):
        raise ValidationError(
            f"check_id '{obj['check_id']}' does not match "
            "^[a-z0-9_-]+/[a-z0-9_.-]+$"
        )

    if not _RE_FINGERPRINT.match(obj["fingerprint"]):
        raise ValidationError(
            f"fingerprint '{obj['fingerprint']}' does not match "
            "^[A-Za-z0-9_.:+/=-]{8,128}$"
        )


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


def coerce_finding(raw: dict, repo_root: str) -> dict:
    """
    Normalise a raw finding dict into a schema-conformant object.
    - Adds/computes fingerprint if absent.
    - Resolves location.path relative to repo_root for context reads.
    - Strips unknown top-level keys (forward-compat).
    """
    # Validate presence of required raw fields before coercing
    required_raw = {
        "check_id", "rule_id", "severity", "confidence",
        "detection", "source", "message", "location",
    }
    missing = required_raw - raw.keys()
    if missing:
        raise ValidationError(f"missing required raw fields: {sorted(missing)}")

    out: dict = {}

    # Required string fields
    for key in ("check_id", "rule_id", "severity", "confidence",
                "detection", "source", "message"):
        out[key] = raw[key]

    # Optional scalar
    if "fix_confidence" in raw:
        out["fix_confidence"] = raw["fix_confidence"]

    # location
    loc_raw = raw["location"]
    if not isinstance(loc_raw, dict):
        raise ValidationError("location must be an object")
    if "path" not in loc_raw or "line" not in loc_raw:
        raise ValidationError("location requires 'path' and 'line'")
    loc: dict = {"path": str(loc_raw["path"]), "line": int(loc_raw["line"])}
    if "end_line" in loc_raw:
        loc["end_line"] = int(loc_raw["end_line"])
    out["location"] = loc

    # fingerprint: keep source-tool value VERBATIM; compute otherwise
    if raw.get("fingerprint"):
        out["fingerprint"] = str(raw["fingerprint"])
    else:
        abs_path = (
            loc["path"]
            if os.path.isabs(loc["path"])
            else os.path.join(repo_root, loc["path"])
        )
        out["fingerprint"] = compute_fingerprint(
            abs_path, loc["line"], raw["message"]
        )

    # Optional structured fields
    if "suppression" in raw:
        out["suppression"] = raw["suppression"]
    if "properties" in raw:
        out["properties"] = raw["properties"]

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # --- Determine input source ---
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        input_path = sys.argv[1]
        try:
            with open(input_path, "r", encoding="utf-8") as fh:
                raw_text = fh.read()
        except OSError as exc:
            print(f"emit-findings: cannot read input file: {exc}", file=sys.stderr)
            return 1
    else:
        raw_text = sys.stdin.read()

    # --- Parse input ---
    try:
        findings_raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"emit-findings: invalid JSON input: {exc}", file=sys.stderr)
        return 1

    if not isinstance(findings_raw, list):
        print("emit-findings: input must be a JSON array", file=sys.stderr)
        return 1

    # --- Determine output path ---
    # Default: .audit/current/findings.jsonl relative to cwd (repo root)
    output_path = os.environ.get(
        "AUDIT_FINDINGS_PATH",
        os.path.join(os.getcwd(), ".audit", "current", "findings.jsonl"),
    )
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    repo_root = os.getcwd()

    # --- Coerce and validate ---
    errors: list = []
    lines: list = []

    for idx, raw in enumerate(findings_raw):
        if not isinstance(raw, dict):
            errors.append(f"finding[{idx}]: must be an object")
            continue
        try:
            finding = coerce_finding(raw, repo_root)
            validate_finding(finding)
            lines.append(json.dumps(finding, separators=(",", ":")))
        except (KeyError, ValidationError) as exc:
            errors.append(f"finding[{idx}]: {exc}")

    if errors:
        for err in errors:
            print(f"emit-findings: {err}", file=sys.stderr)
        return 1

    with open(output_path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")

    print(f"emit-findings: wrote {len(lines)} finding(s) to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
