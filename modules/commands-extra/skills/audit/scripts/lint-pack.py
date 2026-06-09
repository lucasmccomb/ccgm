#!/usr/bin/env python3
"""
CCGM /audit pack linter.

For each packs/*/ directory (excluding _TEMPLATE), validates:
  1. pack.json conforms to pack.schema.json (via registry.py's validate_pack).
  2. checks.md exists and contains all required template sections.
  3. (Optional) If schemas/severity-rubric.json exists, every check-id in pack.json
     has an entry in the rubric. If the rubric is absent, this check is skipped with
     a note.

Exit codes:
  0  All packs pass.
  1  One or more packs have errors.

Usage:
  python3 scripts/lint-pack.py [--packs-dir PATH] [--rubric PATH]

  --packs-dir PATH   Override the packs directory (default: ../packs relative to script).
  --rubric PATH      Override the rubric path (default: ../schemas/severity-rubric.json).
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Required sections that every checks.md must contain.
# Matched case-insensitively via regex against heading lines.
# ---------------------------------------------------------------------------
_REQUIRED_SECTIONS = [
    r"^##\s+Scope",
    r"^##\s+applies_when\s+Rationale",
    r"^##\s+Checks",
    r"^##\s+Quality\s+Checklist",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_registry(scripts_dir: Path):
    """Import registry.py from the scripts directory and return the module."""
    registry_path = scripts_dir / "registry.py"
    if not registry_path.is_file():
        raise FileNotFoundError(f"registry.py not found at {registry_path}")
    spec = importlib.util.spec_from_file_location("registry", str(registry_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_rubric(rubric_path: Path):
    """
    Load the severity rubric if it exists.

    Returns:
        (dict, None)  — rubric loaded as {check_id: entry, ...}
        (None, str)   — rubric absent; second element is a human-readable note
    """
    if not rubric_path.exists():
        return None, f"severity-rubric.json not found at {rubric_path} (Epic 1.5 pending); rubric check skipped"
    try:
        with open(rubric_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        return None, f"severity-rubric.json is not valid JSON: {exc}; rubric check skipped"

    # Rubric is expected to be a list of entries each with an "id" field,
    # or a dict keyed by check-id. Accept both.
    if isinstance(raw, list):
        rubric = {entry["id"]: entry for entry in raw if isinstance(entry, dict) and "id" in entry}
    elif isinstance(raw, dict):
        # Could be {"checks": [...]} envelope, {"checks": {id: entry}} envelope,
        # or a flat {id: entry} map.
        if "checks" in raw and isinstance(raw["checks"], list):
            rubric = {e["id"]: e for e in raw["checks"] if isinstance(e, dict) and "id" in e}
        elif "checks" in raw and isinstance(raw["checks"], dict):
            rubric = raw["checks"]
        else:
            rubric = raw
    else:
        return None, f"Unexpected rubric shape (not list or dict); rubric check skipped"

    return rubric, None


def _check_required_sections(checks_md_path: Path) -> list:
    """
    Return a list of error strings for any required section missing from checks.md.
    """
    try:
        text = checks_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"checks.md: cannot read: {exc}"]

    lines = text.splitlines()
    errors = []
    for pattern in _REQUIRED_SECTIONS:
        compiled = re.compile(pattern, re.IGNORECASE)
        if not any(compiled.match(line) for line in lines):
            # Extract the human-readable section name from the pattern.
            section_name = re.sub(r"\\s\+", " ", pattern).lstrip(r"^#\s+").rstrip("$")
            errors.append(f"checks.md: missing required section matching '{pattern}'")
    return errors


# ---------------------------------------------------------------------------
# Per-pack linting
# ---------------------------------------------------------------------------

def lint_pack(pack_dir: Path, registry_mod, rubric, rubric_note: str) -> list:
    """
    Lint a single pack directory. Returns a (possibly empty) list of error strings.
    """
    errors = []

    # ---- 1. pack.json schema validation ----
    pack_json_path = pack_dir / "pack.json"
    if not pack_json_path.is_file():
        errors.append("pack.json: missing")
        # Without pack.json, skip checks that depend on its contents.
        # Still validate checks.md structure below.
    else:
        try:
            with open(pack_json_path, encoding="utf-8") as fh:
                pack = json.load(fh)
        except json.JSONDecodeError as exc:
            errors.append(f"pack.json: invalid JSON: {exc}")
            pack = None

        if pack is not None:
            try:
                registry_mod.validate_pack(pack, str(pack_json_path))
            except registry_mod.ValidationError as exc:
                errors.append(f"pack.json: schema validation failed: {exc}")

            # Collect check-ids for rubric cross-check (done below).
            check_ids = [c["id"] for c in pack.get("checks", []) if isinstance(c, dict) and "id" in c]
        else:
            check_ids = []

    # ---- 2. checks.md required sections ----
    checks_md_path = pack_dir / "checks.md"
    if not checks_md_path.is_file():
        errors.append("checks.md: missing")
    else:
        section_errors = _check_required_sections(checks_md_path)
        errors.extend(section_errors)

    # ---- 3. Rubric membership (optional — only when rubric is present) ----
    if rubric is None:
        # Note (not an error): emit once per pack so output is clear.
        # Callers handle the note separately; skip here.
        pass
    elif pack_json_path.is_file() and pack is not None:
        for cid in check_ids:
            if cid not in rubric:
                errors.append(
                    f"pack.json: check '{cid}' has no entry in severity-rubric.json"
                )

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Lint /audit check packs for schema conformance and template completeness."
    )
    parser.add_argument(
        "--packs-dir",
        default=None,
        help="Path to the packs/ directory. Default: ../packs relative to this script.",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        help="Path to severity-rubric.json. Default: ../schemas/severity-rubric.json. "
             "If absent, rubric membership check is skipped.",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).parent.resolve()
    audit_dir = script_dir.parent

    packs_dir = Path(args.packs_dir) if args.packs_dir else audit_dir / "packs"
    rubric_path = Path(args.rubric) if args.rubric else audit_dir / "schemas" / "severity-rubric.json"

    # Load registry module (for validate_pack + ValidationError).
    try:
        registry_mod = _load_registry(script_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Load rubric (optional).
    rubric, rubric_note = _load_rubric(rubric_path)
    if rubric_note:
        print(f"NOTE: {rubric_note}")

    # Discover pack directories (exclude _TEMPLATE).
    if not packs_dir.is_dir():
        print(f"NOTE: packs directory not found at {packs_dir}; nothing to lint.")
        return 0

    pack_dirs = sorted(
        d for d in packs_dir.iterdir()
        if d.is_dir() and d.name != "_TEMPLATE"
    )

    if not pack_dirs:
        print(f"NOTE: no packs found under {packs_dir} (excluding _TEMPLATE); nothing to lint.")
        return 0

    # Lint each pack.
    total_errors = 0
    for pack_dir in pack_dirs:
        errors = lint_pack(pack_dir, registry_mod, rubric, rubric_note)
        if errors:
            print(f"\nFAIL: {pack_dir.name}")
            for err in errors:
                print(f"  ERROR: {err}")
            total_errors += len(errors)
        else:
            print(f"PASS: {pack_dir.name}")

    # Summary.
    print(f"\n{len(pack_dirs)} pack(s) checked, {total_errors} error(s).")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
