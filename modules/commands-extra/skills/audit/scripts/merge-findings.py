#!/usr/bin/env python3
"""
CCGM /audit merge-findings (Epic 1.9) -- spine + LLM results merger.

Merges the deterministic spine JSONL with zero or more LLM results files,
applies triage verdicts, deduplicates by fingerprint, enforces the severity
rubric mechanically, and streams schema-valid JSONL to stdout (or --output).

Usage
-----
  merge-findings.py --spine <spine.jsonl> [--llm <results.json> ...] \
                    [--rubric <path>] [--output <path>]

Arguments
---------
  --spine   <path>   Required. JSONL produced by scripts/spine/run.sh.
  --llm     <path>   Zero or more LLM results JSON files (see contract below).
                     Pass the flag multiple times for multiple workers.
  --rubric  <path>   Path to severity-rubric.json.
                     Default: ../schemas/severity-rubric.json relative to this script.
  --output  <path>   Write merged JSONL to this file. Default: stdout.

Exit codes
----------
  0  Success.
  1  Malformed input or validation error.

LLM results-file contract
--------------------------
Each --llm file is a JSON object with two keys:

  {
    "findings": [
      {
        "check_id":      str,   e.g. "security/hardcoded-secret"
        "rule_id":       str,
        "severity":      str,   critical|high|medium|low|info
        "confidence":    str,   high|medium|low
        "detection":     str,   tool|llm|hybrid
        "source":        str,   "llm" (worker-produced findings must be "llm")
        "message":       str,
        "location":      {"path": str, "line": int},
        // Optional:
        "fingerprint":   str,   If present, kept VERBATIM.
        "fix_confidence":str,
        "properties":    {}
      }
    ],
    "spine_triage": [
      {
        "fingerprint": str,     Fingerprint of a spine hybrid candidate.
        "verdict":     str,     "confirmed" | "dismissed"
        "note":        str      Optional human-readable explanation.
      }
    ]
  }

Workers produce this file by:
  1. Reading their spine-slice (ABSOLUTE path in their task file).
  2. For each finding with detection="hybrid": deciding confirmed/dismissed.
  3. Adding any llm-only findings to "findings".
  4. Never inventing severity -- rubric lookup only (merge-findings enforces it).

Merge semantics (in order)
---------------------------
1.  Parse spine JSONL: separate provenance records, note records (type field
    present), and finding records (no type field).
2.  Parse each LLM results file; collect findings + triage verdicts.
3.  Ensure every finding has a fingerprint: tool-supplied fingerprints kept
    VERBATIM; fingerprints missing get compute_fingerprint() via the imported
    emit-findings logic (same fallback: message+location when file unreadable).
4.  Triage:
      - Drop detection="hybrid" findings whose fingerprint has verdict "dismissed".
      - detection="tool" and detection="llm" findings are NOT dismissible.
        If a triage verdict targets a non-hybrid finding, warn to stderr and skip
        the verdict (the finding is kept).
      - detection="hybrid" with "confirmed" verdict is kept (same as no verdict --
        the default is keep; dismissed is the only active action).
5.  Dedup by fingerprint: when a tool finding and an LLM finding share a
    fingerprint, keep the tool finding (source=tool; deterministic wins).
    Order output deterministically: sort by location.path, then location.line,
    then check_id.
6.  Mechanical rubric enforcement for every finding:
      - check_id IN rubric: overwrite severity, confidence, fix_confidence with
        rubric values. If the overwritten severity DIFFERS from what the finding
        carried, preserve the original as properties.agentReportedSeverity (ADV-007).
      - check_id NOT IN rubric: keep reported severity, force confidence="low",
        set properties.unrubriced=True.
7.  Output: provenance record(s) first, then merged schema-valid findings (one
    JSON object per line), then coverage_gap records (deduped by byte-identity).
    Every finding line is validated; invalid findings cause exit 1.
"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import emit-findings.py via importlib (hyphenated filename)
# Pattern from lint-pack.py's _load_registry helper.
# ---------------------------------------------------------------------------

def _load_emit_findings(scripts_dir: Path):
    """Import emit-findings.py and return the module."""
    emit_path = scripts_dir / "emit-findings.py"
    if not emit_path.is_file():
        raise FileNotFoundError(f"emit-findings.py not found at {emit_path}")
    spec = importlib.util.spec_from_file_location("emit_findings", str(emit_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------

def _load_rubric(rubric_path: Path) -> dict:
    """
    Load severity-rubric.json and return the checks dict.
    Returns {} if the file is absent or unreadable (non-fatal -- unrubriced
    path handles missing entries gracefully).
    """
    if not rubric_path.exists():
        print(
            f"merge-findings: WARNING: rubric not found at {rubric_path}; "
            "all findings will be treated as unrubriced",
            file=sys.stderr,
        )
        return {}
    try:
        with open(rubric_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"merge-findings: WARNING: rubric JSON decode error: {exc}; "
            "treating all findings as unrubriced",
            file=sys.stderr,
        )
        return {}
    if isinstance(raw, dict) and "checks" in raw:
        return raw["checks"]
    if isinstance(raw, dict):
        return raw
    return {}


# ---------------------------------------------------------------------------
# Spine JSONL parsing
# ---------------------------------------------------------------------------

def _parse_spine(spine_path: str):
    """
    Parse the spine JSONL file.

    Returns:
        provenance_records  list of dicts with "type" == "provenance"
        note_records        list of dicts with any "type" field (skipped, coverage_gap, etc.)
        findings            list of finding dicts (no "type" field)
    """
    provenance_records = []
    note_records = []
    findings = []

    try:
        with open(spine_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"merge-findings: ERROR: cannot read spine file: {exc}", file=sys.stderr)
        sys.exit(1)

    for lineno, raw_line in enumerate(lines, 1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            print(
                f"merge-findings: ERROR: spine line {lineno} is not valid JSON: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not isinstance(obj, dict):
            print(
                f"merge-findings: ERROR: spine line {lineno} is not a JSON object",
                file=sys.stderr,
            )
            sys.exit(1)

        if "type" in obj:
            if obj["type"] == "provenance":
                provenance_records.append(obj)
            else:
                note_records.append(obj)
        else:
            findings.append(obj)

    return provenance_records, note_records, findings


# ---------------------------------------------------------------------------
# LLM results file parsing
# ---------------------------------------------------------------------------

def _parse_llm_file(llm_path: str):
    """
    Parse a single LLM results file.

    Returns:
        llm_findings   list of finding dicts
        triage_map     dict of fingerprint -> verdict ("confirmed" | "dismissed")
        triage_notes   dict of fingerprint -> optional note
    """
    try:
        with open(llm_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        print(
            f"merge-findings: ERROR: cannot read LLM results file {llm_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"merge-findings: ERROR: LLM results file {llm_path} is not valid JSON: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(raw, dict):
        print(
            f"merge-findings: ERROR: LLM results file {llm_path} must be a JSON object",
            file=sys.stderr,
        )
        sys.exit(1)

    llm_findings = raw.get("findings", [])
    if not isinstance(llm_findings, list):
        print(
            f"merge-findings: ERROR: {llm_path}: 'findings' must be an array",
            file=sys.stderr,
        )
        sys.exit(1)

    triage_list = raw.get("spine_triage", [])
    if not isinstance(triage_list, list):
        print(
            f"merge-findings: ERROR: {llm_path}: 'spine_triage' must be an array",
            file=sys.stderr,
        )
        sys.exit(1)

    triage_map = {}
    triage_notes = {}
    for entry in triage_list:
        if not isinstance(entry, dict):
            continue
        fp = entry.get("fingerprint", "")
        verdict = entry.get("verdict", "")
        if fp and verdict in ("confirmed", "dismissed"):
            triage_map[fp] = verdict
            if "note" in entry:
                triage_notes[fp] = entry["note"]

    return llm_findings, triage_map, triage_notes


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------

def _ensure_fingerprint(finding: dict, emit_mod) -> dict:
    """
    Ensure the finding has a fingerprint.
    Tool-supplied fingerprints are kept VERBATIM.
    Missing fingerprints are computed via emit-findings' compute_fingerprint.
    """
    if finding.get("fingerprint"):
        return finding

    loc = finding.get("location", {})
    path = loc.get("path", "")
    line = loc.get("line", 1)
    message = finding.get("message", "")

    finding["fingerprint"] = emit_mod.compute_fingerprint(
        path, line, message
    )
    return finding


# ---------------------------------------------------------------------------
# Rubric enforcement
# ---------------------------------------------------------------------------

def _apply_rubric(finding: dict, rubric: dict) -> dict:
    """
    Apply mechanical rubric enforcement.

    check_id IN rubric:
      - Overwrite severity, confidence, fix_confidence with rubric values.
      - If overwritten severity differs from reported: preserve original in
        properties.agentReportedSeverity.

    check_id NOT IN rubric:
      - Keep reported severity.
      - Force confidence = "low".
      - Set properties.unrubriced = True.
    """
    check_id = finding.get("check_id", "")
    if check_id in rubric:
        entry = rubric[check_id]
        reported_severity = finding.get("severity")
        rubric_severity = entry.get("severity", reported_severity)

        if rubric_severity != reported_severity:
            props = finding.get("properties") or {}
            props["agentReportedSeverity"] = reported_severity
            finding["properties"] = props

        finding["severity"] = rubric_severity
        if "confidence" in entry:
            finding["confidence"] = entry["confidence"]
        if "fix_confidence" in entry:
            finding["fix_confidence"] = entry["fix_confidence"]
    else:
        finding["confidence"] = "low"
        props = finding.get("properties") or {}
        props["unrubriced"] = True
        finding["properties"] = props

    return finding


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    script_dir = Path(__file__).parent

    # ------------------------------------------------------------------
    # Argument parsing
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Merge spine JSONL with LLM results, apply triage + rubric.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--spine", required=True, help="Path to spine.jsonl")
    parser.add_argument(
        "--llm",
        action="append",
        default=[],
        metavar="PATH",
        help="LLM results JSON file (may be repeated)",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        help="Path to severity-rubric.json (default: ../schemas/severity-rubric.json)",
    )
    parser.add_argument("--output", default=None, help="Output path (default: stdout)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load emit-findings module for fingerprint + validation
    # ------------------------------------------------------------------
    try:
        emit_mod = _load_emit_findings(script_dir)
    except FileNotFoundError as exc:
        print(f"merge-findings: ERROR: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Load rubric
    # ------------------------------------------------------------------
    if args.rubric:
        rubric_path = Path(args.rubric)
    else:
        rubric_path = script_dir / ".." / "schemas" / "severity-rubric.json"
    rubric_path = rubric_path.resolve()
    rubric = _load_rubric(rubric_path)

    # ------------------------------------------------------------------
    # Step 1: Parse spine
    # ------------------------------------------------------------------
    provenance_records, note_records, spine_findings = _parse_spine(args.spine)

    # ------------------------------------------------------------------
    # Step 2: Parse LLM results files
    # ------------------------------------------------------------------
    all_llm_findings = []
    merged_triage_map = {}  # fingerprint -> verdict

    for llm_path in args.llm:
        llm_findings, triage_map, _ = _parse_llm_file(llm_path)
        all_llm_findings.extend(llm_findings)
        merged_triage_map.update(triage_map)

    # ------------------------------------------------------------------
    # Step 3: Ensure all findings have fingerprints
    # ------------------------------------------------------------------
    for f in spine_findings:
        _ensure_fingerprint(f, emit_mod)
    for f in all_llm_findings:
        _ensure_fingerprint(f, emit_mod)

    # ------------------------------------------------------------------
    # Step 4: Apply triage verdicts
    # ------------------------------------------------------------------
    # Validate triage targets: warn if a triage verdict targets a non-hybrid finding
    all_findings_for_triage = spine_findings + all_llm_findings
    fp_to_detection = {}
    for f in all_findings_for_triage:
        fp = f.get("fingerprint", "")
        if fp:
            fp_to_detection[fp] = f.get("detection", "tool")

    for fp, verdict in merged_triage_map.items():
        if fp in fp_to_detection:
            detection = fp_to_detection[fp]
            if detection != "hybrid":
                print(
                    f"merge-findings: WARNING: triage verdict '{verdict}' targets "
                    f"a non-hybrid finding (detection='{detection}', fp='{fp}'); "
                    "verdict ignored -- deterministic findings are not dismissible",
                    file=sys.stderr,
                )

    # Filter: drop dismissed hybrids
    def _keep_finding(f: dict) -> bool:
        detection = f.get("detection", "tool")
        if detection != "hybrid":
            return True
        fp = f.get("fingerprint", "")
        verdict = merged_triage_map.get(fp)
        return verdict != "dismissed"

    spine_findings = [f for f in spine_findings if _keep_finding(f)]
    all_llm_findings = [f for f in all_llm_findings if _keep_finding(f)]

    # ------------------------------------------------------------------
    # Step 5: Dedup by fingerprint -- tool source wins over llm source
    # ------------------------------------------------------------------
    # Build a dict keyed by fingerprint; tool findings win.
    by_fingerprint: dict = {}

    # Insert LLM findings first (lower priority)
    for f in all_llm_findings:
        fp = f.get("fingerprint", "")
        if fp and fp not in by_fingerprint:
            by_fingerprint[fp] = f

    # Insert spine (tool) findings, overwriting any LLM finding with same fp
    for f in spine_findings:
        fp = f.get("fingerprint", "")
        if fp:
            by_fingerprint[fp] = f  # tool always wins
        else:
            # No fingerprint (should not happen after step 3): keep as unique
            import hashlib as _hl
            sentinel = _hl.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:16]
            by_fingerprint[sentinel] = f

    merged = list(by_fingerprint.values())

    # Deterministic sort: path, line, check_id
    def _sort_key(f: dict):
        loc = f.get("location", {})
        return (
            loc.get("path", ""),
            loc.get("line", 0),
            f.get("check_id", ""),
        )

    merged.sort(key=_sort_key)

    # ------------------------------------------------------------------
    # Step 6: Mechanical rubric enforcement
    # ------------------------------------------------------------------
    for f in merged:
        _apply_rubric(f, rubric)

    # ------------------------------------------------------------------
    # Step 6b: Ensure all merged findings have required fields for validation.
    # Spine findings already conform; LLM findings may be missing rule_id
    # or other fields. We do a best-effort coerce before validation.
    # ------------------------------------------------------------------
    for f in merged:
        if "rule_id" not in f:
            f["rule_id"] = f.get("check_id", "unknown")

    # ------------------------------------------------------------------
    # Validate each merged finding
    # ------------------------------------------------------------------
    errors = []
    valid_findings = []
    for idx, f in enumerate(merged):
        try:
            emit_mod.validate_finding(f)
            valid_findings.append(f)
        except emit_mod.ValidationError as exc:
            errors.append(f"finding[{idx}] ({f.get('check_id','?')}): {exc}")

    if errors:
        for err in errors:
            print(f"merge-findings: VALIDATION ERROR: {err}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Step 7: Build output lines
    # ------------------------------------------------------------------
    output_lines = []

    # Provenance first
    for rec in provenance_records:
        output_lines.append(json.dumps(rec, separators=(",", ":")))

    # Findings
    for f in valid_findings:
        output_lines.append(json.dumps(f, separators=(",", ":")))

    # Coverage gaps (dedup byte-identical lines)
    seen_gaps = set()
    for rec in note_records:
        if rec.get("type") == "coverage_gap":
            serialized = json.dumps(rec, separators=(",", ":"), sort_keys=True)
            if serialized not in seen_gaps:
                seen_gaps.add(serialized)
                output_lines.append(json.dumps(rec, separators=(",", ":")))

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    out_text = "\n".join(output_lines)
    if output_lines:
        out_text += "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_text(out_text, encoding="utf-8")
        except OSError as exc:
            print(f"merge-findings: ERROR: cannot write output: {exc}", file=sys.stderr)
            return 1
        print(
            f"merge-findings: wrote {len(valid_findings)} finding(s) + "
            f"{len(seen_gaps)} coverage-gap(s) to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
