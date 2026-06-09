#!/usr/bin/env python3
"""
CCGM /audit merge-findings (Epic 1.9) -- spine + LLM results merger.

Merges the deterministic spine JSONL with zero or more LLM results files,
applies triage verdicts, deduplicates by fingerprint, enforces the severity
rubric mechanically, and streams schema-valid JSONL to stdout (or --output).

Usage
-----
  merge-findings.py --spine <spine.jsonl> [--llm <results.json> ...] \\
                    [--rubric <path>] [--repo <abs-path>] [--output <path>]

Arguments
---------
  --spine   <path>   Required. JSONL produced by scripts/spine/run.sh.
  --llm     <path>   Zero or more LLM results JSON files (see contract below).
                     Pass the flag multiple times for multiple workers.
  --rubric  <path>   Path to severity-rubric.json.
                     Default: ../schemas/severity-rubric.json relative to this script.
  --repo    <path>   Absolute path to the repository root.
                     Used to resolve location.path when computing fingerprints so
                     fingerprints are cwd-independent (matching emit-findings.py).
                     Default: current working directory.
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
        "rule_id":       str,   Optional for llm findings -- defaults to check_id when absent.
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
  1. Reading their spine-slice (ABSOLUTE path embedded in their task file as spine_slice_path).
  2. For each finding with detection="hybrid": deciding confirmed/dismissed.
  3. Adding any llm-only findings to "findings".
  4. Never inventing severity -- rubric lookup only (merge-findings enforces it).

Worker trust-boundary invariants (enforced at intake, not just documented):
  - A results file missing BOTH "findings" and "spine_triage" keys is likely a typo'd
    key; a warning is printed naming the file so the problem is not silently swallowed.
  - Workers must claim source="llm". A finding claiming source="tool" is coerced to
    "llm" with a stderr warning (deterministic-standing masquerade).
  - Workers must claim detection="llm" or detection="hybrid". A finding claiming
    detection="tool" is coerced to detection="llm" with a stderr warning (a worker
    claiming tool-detection would otherwise become non-dismissible).

Merge semantics (in order)
---------------------------
1.  Parse spine JSONL: separate provenance records, note records (type field
    present), and finding records (no type field).
2.  Parse each LLM results file; collect findings + triage verdicts.
    - Enforce worker trust-boundary invariants at intake (see above).
    - Within a single results file, duplicate fingerprints: first entry wins (the
      second is a worker-side bug; the warning gate in step 4 will flag the triage
      target).
    - Across results files, conflicting verdicts for the same fingerprint: KEEP the
      finding (dismissal requires unanimity across all workers). A warning names the
      conflicting fingerprint.
3.  Ensure every finding has a fingerprint: tool-supplied fingerprints kept
    VERBATIM; fingerprints missing get compute_fingerprint() via the imported
    emit-findings logic (same fallback: message+location when file unreadable).
    Paths are resolved relative to --repo so fingerprints are cwd-independent.
4.  Triage:
      - Drop detection="hybrid" findings whose fingerprint was unanimously
        "dismissed" across every results file that named that fingerprint.
      - detection="tool" and detection="llm" findings are NOT dismissible.
        If a triage verdict targets a non-hybrid finding, warn to stderr and skip
        the verdict (the finding is kept).
      - A triage fingerprint that matches no finding: warn to stderr.
      - An unknown verdict string (not "confirmed" / "dismissed"): warn to stderr,
        treat as no-op (never honor unknown verdicts).
      - detection="hybrid" with "confirmed" verdict is kept (same as no verdict --
        the default is keep; dismissed is the only active action).
5.  Dedup by fingerprint: when a tool finding and an LLM finding share a
    fingerprint, keep the tool finding (source=tool; deterministic wins).
    Within each source group (tool or llm), first-seen fingerprint wins.
    Order output deterministically: sort by location.path, then location.line,
    then check_id.
6.  Validate findings BEFORE sort and rubric steps so malformed input (e.g.
    "line": "7" as a string) exits 1 through the actionable-error channel instead
    of a bare TypeError traceback from merged.sort().
7.  Mechanical rubric enforcement for every finding:
      - check_id IN rubric: overwrite severity, confidence, fix_confidence with
        rubric values. If the overwritten severity DIFFERS from what the finding
        carried, preserve the original as properties.agentReportedSeverity (ADV-007).
      - check_id NOT IN rubric: keep reported severity, force confidence="low",
        set properties.unrubriced=True.
8.  Output: provenance record(s) first, then merged schema-valid findings (one
    JSON object per line), then coverage_gap records (deduped by byte-identity).
    Every finding line is validated; invalid findings cause exit 1.
"""

import argparse
import importlib.util
import json
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

_KNOWN_VERDICTS = frozenset({"confirmed", "dismissed"})


def _parse_llm_file(llm_path: str):
    """
    Parse a single LLM results file.

    Enforces worker trust-boundary invariants at intake:
      - Missing both "findings" and "spine_triage" keys: stderr warning naming the file.
      - source="tool" on a worker finding: coerced to "llm" with a warning.
      - detection="tool" on a worker finding: coerced to "llm" with a warning.
      - Unknown verdict strings: stderr warning, entry skipped (never honored).
      - First-wins on duplicate fingerprints within this file.

    Returns:
        llm_findings   list of finding dicts (trust-boundary coercions applied)
        triage_map     dict of fingerprint -> verdict ("confirmed" | "dismissed")
                       Only well-known verdicts for non-duplicate fingerprints are included.
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

    # Fix #1: warn if neither key is present (likely a typo'd key).
    if "findings" not in raw and "spine_triage" not in raw:
        print(
            f"merge-findings: WARNING: LLM results file {llm_path} contains neither "
            "'findings' nor 'spine_triage' keys -- possible typo'd key; file ignored",
            file=sys.stderr,
        )
        return [], {}

    llm_findings_raw = raw.get("findings", [])
    if not isinstance(llm_findings_raw, list):
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

    # Fix #5: enforce worker trust-boundary coercions on findings.
    llm_findings = []
    for f in llm_findings_raw:
        if not isinstance(f, dict):
            continue
        claimed_source = f.get("source", "")
        if claimed_source == "tool":
            print(
                f"merge-findings: WARNING: {llm_path}: worker finding claims "
                f"source='tool' (deterministic-standing masquerade); coercing to 'llm'",
                file=sys.stderr,
            )
            f = dict(f)
            f["source"] = "llm"
        claimed_detection = f.get("detection", "")
        if claimed_detection == "tool":
            print(
                f"merge-findings: WARNING: {llm_path}: worker finding claims "
                f"detection='tool'; coercing to 'llm' (a worker claiming tool-detection "
                "would otherwise become non-dismissible)",
                file=sys.stderr,
            )
            f = dict(f)
            f["detection"] = "llm"
        llm_findings.append(f)

    # Build triage_map; warn on unknown verdicts; first-wins on duplicate fingerprints
    # within this file.
    triage_map: dict = {}
    for entry in triage_list:
        if not isinstance(entry, dict):
            continue
        fp = entry.get("fingerprint", "")
        verdict = entry.get("verdict", "")

        # Fix #2: warn on unknown verdict strings, never honor them.
        if verdict not in _KNOWN_VERDICTS:
            print(
                f"merge-findings: WARNING: {llm_path}: unknown triage verdict "
                f"'{verdict}' for fingerprint '{fp}'; treating as no-op",
                file=sys.stderr,
            )
            continue

        if not fp:
            continue

        # First-wins within this file (within-source dedup rule).
        if fp not in triage_map:
            triage_map[fp] = verdict

    return llm_findings, triage_map


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------

def _ensure_fingerprint(finding: dict, emit_mod, repo_root: Path) -> dict:
    """
    Ensure the finding has a fingerprint.
    Tool-supplied fingerprints are kept VERBATIM.
    Missing fingerprints are computed via emit-findings' compute_fingerprint.
    Paths are resolved relative to repo_root so fingerprints are cwd-independent.
    """
    if finding.get("fingerprint"):
        return finding

    loc = finding.get("location", {})
    path = loc.get("path", "")
    line = loc.get("line", 1)
    message = finding.get("message", "")

    # Resolve path relative to repo_root for cwd-independent fingerprints.
    abs_path = str(repo_root / path) if path and not Path(path).is_absolute() else path

    finding["fingerprint"] = emit_mod.compute_fingerprint(
        abs_path, line, message
    )
    return finding


# ---------------------------------------------------------------------------
# Pre-sort validation helper
# ---------------------------------------------------------------------------

def _validate_before_sort(findings: list, emit_mod) -> list:
    """
    Validate findings BEFORE sort and rubric steps (Fix #6).

    Exits 1 with an actionable error message if any finding is malformed
    (e.g. location.line is a string instead of an int), so the user sees
    a clear ERROR rather than a bare TypeError traceback from merged.sort().

    Returns validated findings (unchanged list if all pass).
    """
    errors = []
    for idx, f in enumerate(findings):
        loc = f.get("location", {})
        line_val = loc.get("line") if isinstance(loc, dict) else None
        if line_val is not None and not isinstance(line_val, int):
            errors.append(
                f"finding[{idx}] ({f.get('check_id','?')}): "
                f"location.line must be an integer, got {type(line_val).__name__} "
                f"value {line_val!r}"
            )
        # Also run the full validation to catch any other malformed fields early.
        try:
            emit_mod.validate_finding(f)
        except emit_mod.ValidationError as exc:
            errors.append(f"finding[{idx}] ({f.get('check_id','?')}): {exc}")

    if errors:
        for err in errors:
            print(f"merge-findings: VALIDATION ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    return findings


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
    parser.add_argument(
        "--repo",
        default=None,
        metavar="ABS_PATH",
        help=(
            "Absolute path to the repository root. Used to resolve location.path "
            "when computing fingerprints so fingerprints are cwd-independent "
            "(matching emit-findings.py). Default: current working directory."
        ),
    )
    parser.add_argument("--output", default=None, help="Output path (default: stdout)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve repo root
    # ------------------------------------------------------------------
    if args.repo:
        repo_root = Path(args.repo).resolve()
    else:
        repo_root = Path.cwd()

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
    # Step 2: Parse LLM results files.
    # Collect per-file triage maps to detect cross-file conflicts.
    # Dismissal requires unanimity: a fingerprint is dismissed only if
    # EVERY file that named it voted "dismissed".
    # ------------------------------------------------------------------
    all_llm_findings: list = []
    # per_file_triage: list of (llm_path, triage_map) for conflict detection
    per_file_triage: list = []

    for llm_path in args.llm:
        llm_findings, triage_map = _parse_llm_file(llm_path)
        all_llm_findings.extend(llm_findings)
        per_file_triage.append((llm_path, triage_map))

    # Build the merged triage map with conflict detection (Fix #4).
    # For each fingerprint that appears in any file:
    #   - All votes "dismissed" -> dismissed.
    #   - Any vote "confirmed" or conflict -> confirmed (kept); warn if conflict.
    merged_triage_map: dict = {}  # fingerprint -> "dismissed" | "confirmed"
    fp_votes: dict = {}  # fp -> list of (path, verdict)
    for llm_path, tmap in per_file_triage:
        for fp, verdict in tmap.items():
            fp_votes.setdefault(fp, []).append((llm_path, verdict))

    for fp, votes in fp_votes.items():
        verdicts = [v for _, v in votes]
        unique_verdicts = set(verdicts)
        if len(unique_verdicts) == 1:
            merged_triage_map[fp] = verdicts[0]
        else:
            # Fix #4: conflicting verdicts -> keep + warn.
            sources = ", ".join(f"'{v}' from {p}" for p, v in votes)
            print(
                f"merge-findings: WARNING: conflicting triage verdicts for "
                f"fingerprint '{fp}' ({sources}); keeping finding "
                "(dismissal requires unanimity across all workers)",
                file=sys.stderr,
            )
            merged_triage_map[fp] = "confirmed"

    # ------------------------------------------------------------------
    # Step 3: Ensure all findings have fingerprints
    # ------------------------------------------------------------------
    for f in spine_findings:
        _ensure_fingerprint(f, emit_mod, repo_root)
    for f in all_llm_findings:
        _ensure_fingerprint(f, emit_mod, repo_root)

    # ------------------------------------------------------------------
    # Step 4: Apply triage verdicts
    # ------------------------------------------------------------------
    # Build fp -> detection map from all findings for triage validation.
    all_findings_for_triage = spine_findings + all_llm_findings
    fp_to_detection: dict = {}
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
        else:
            # Fix #3: triage fingerprint matches no finding -> warn.
            print(
                f"merge-findings: WARNING: triage fingerprint '{fp}' (verdict='{verdict}') "
                "does not match any finding in the spine or LLM results; verdict ignored",
                file=sys.stderr,
            )

    # Filter: drop hybrid findings that were unanimously dismissed.
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
    # Step 5: Dedup by fingerprint -- tool source wins over llm source.
    # Within each source group, first-seen fingerprint wins.
    # ------------------------------------------------------------------
    by_fingerprint: dict = {}

    # Insert LLM findings first (lower priority); first-wins within this group.
    for f in all_llm_findings:
        fp = f.get("fingerprint", "")
        if fp and fp not in by_fingerprint:
            by_fingerprint[fp] = f

    # Insert spine (tool) findings, overwriting any LLM finding with same fp.
    # First-seen wins within the spine group (spine is already deterministic).
    for f in spine_findings:
        fp = f.get("fingerprint", "")
        if fp:
            by_fingerprint[fp] = f  # tool always wins over llm

    merged = list(by_fingerprint.values())

    # ------------------------------------------------------------------
    # Step 5b: Ensure all merged findings have required fields for validation.
    # Spine findings already conform; LLM findings may be missing rule_id
    # or other fields. We do a best-effort coerce before validation.
    # ------------------------------------------------------------------
    for f in merged:
        if "rule_id" not in f:
            f["rule_id"] = f.get("check_id", "unknown")

    # ------------------------------------------------------------------
    # Step 6: Validate findings BEFORE sort and rubric (Fix #6).
    # Exits 1 with an actionable message on malformed input (e.g. string line)
    # instead of a bare TypeError traceback from merged.sort().
    # ------------------------------------------------------------------
    merged = _validate_before_sort(merged, emit_mod)

    # ------------------------------------------------------------------
    # Deterministic sort: path, line, check_id
    # ------------------------------------------------------------------
    def _sort_key(f: dict):
        loc = f.get("location", {})
        return (
            loc.get("path", ""),
            loc.get("line", 0),
            f.get("check_id", ""),
        )

    merged.sort(key=_sort_key)

    # ------------------------------------------------------------------
    # Step 7: Mechanical rubric enforcement
    # ------------------------------------------------------------------
    for f in merged:
        _apply_rubric(f, rubric)

    # ------------------------------------------------------------------
    # Final validation pass (post-rubric)
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
    # Step 8: Build output lines
    # ------------------------------------------------------------------
    output_lines = []

    # Provenance first
    for rec in provenance_records:
        output_lines.append(json.dumps(rec, separators=(",", ":")))

    # Findings
    for f in valid_findings:
        output_lines.append(json.dumps(f, separators=(",", ":")))

    # Coverage gaps (dedup byte-identical lines)
    seen_gaps: set = set()
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
