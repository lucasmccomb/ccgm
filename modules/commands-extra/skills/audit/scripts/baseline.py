#!/usr/bin/env python3
"""
CCGM /audit baseline classifier (Epic 3.2).

Classifies current audit findings as new, existing, or resolved by comparing
against a baseline findings.jsonl produced by a previous merge-findings run.

Usage
-----
  baseline.py --current <findings.jsonl> --baseline <file> \\
              [--new-only] [--output <file>] [--save-baseline <path>]

Arguments
---------
  --current   <path>  Required. Current findings.jsonl (merge-findings output).
  --baseline  <path>  Required. Baseline findings.jsonl to compare against.
                      Must be a file path to a previous merge-findings output.
                      Ref-resolution (e.g. a git SHA) is not supported by this
                      script; to compare against a ref, extract the findings.jsonl
                      from that ref first:
                        git show <ref>:.audit/current/findings.jsonl > baseline.jsonl
                      then pass the extracted file here.
  --new-only          Optional. If set, output only findings tagged "new" (plus
                      the baseline_summary record). Findings tagged "existing" and
                      resolved records are omitted from output.
  --output    <path>  Optional. Write output JSONL to this file instead of stdout.
  --save-baseline <path>
                      Optional. Copy the current findings.jsonl to <path> after
                      classification. Useful for persisting the current run as the
                      next baseline (e.g. --save-baseline .audit/history/YYYY-MM-DD.jsonl).
                      The copy is byte-identical to --current; the baseline_summary
                      record written to --output is NOT included in the saved file.

Input format (both --current and --baseline)
--------------------------------------------
JSONL produced by merge-findings.py. Each line is one of:
  - A finding record (no "type" field): has "rule_id" and "fingerprint".
  - A metadata record (has a "type" field): provenance, coverage_gap, etc.

Only finding records (those without a "type" field) participate in matching.
Metadata records in --current are passed through to output unchanged; metadata
records in --baseline are ignored.

Matching key
------------
(rule_id, fingerprint)

Classification
--------------
Each current finding is tagged in properties.baseline_status:
  "new"      — present in current, absent from baseline.
  "existing" — present in both current and baseline.

Additionally, baseline findings absent from current are emitted as:
  {"type": "resolved", "rule_id": ..., "fingerprint": ..., "baseline": <path>}
These represent findings that were fixed since the baseline was captured.

Summary record
--------------
A {"type": "baseline_summary", "new": N, "existing": N, "resolved": N, "baseline": <path>}
record is always emitted as the first line of output.

Output order
------------
1. baseline_summary record
2. Metadata records from --current (provenance, coverage_gap, etc.) — passed through
3. Tagged finding records (all, or only "new" when --new-only)
4. Resolved records (omitted when --new-only)

History / save-baseline pattern
--------------------------------
To maintain a run history, pass --save-baseline each time:
  baseline.py --current .audit/current/findings.jsonl \\
              --baseline .audit/history/last.jsonl \\
              --save-baseline .audit/history/$(date +%Y-%m-%d).jsonl
The script copies --current to the save path AFTER classification, so the saved
file is the verbatim merge-findings output without baseline_status tags.

Exit codes
----------
  0  Success.
  1  Input error, file not found, or malformed JSONL.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# JSONL loading helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: str, label: str):
    """
    Load a JSONL file and return (metadata_records, finding_records).

    metadata_records  list of dicts that have a "type" field
    finding_records   list of dicts without a "type" field

    Exits 1 with a clear stderr message on any IO or parse error.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(
            f"baseline: ERROR: cannot read {label} file '{path}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    metadata_records = []
    finding_records = []

    for lineno, raw_line in enumerate(raw_lines, 1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            print(
                f"baseline: ERROR: {label} '{path}' line {lineno} is not valid JSON: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not isinstance(obj, dict):
            print(
                f"baseline: ERROR: {label} '{path}' line {lineno} is not a JSON object",
                file=sys.stderr,
            )
            sys.exit(1)

        if "type" in obj:
            metadata_records.append(obj)
        else:
            finding_records.append(obj)

    return metadata_records, finding_records


# ---------------------------------------------------------------------------
# Matching key
# ---------------------------------------------------------------------------

def _match_key(finding: dict):
    """Return the (rule_id, fingerprint) tuple used for baseline matching."""
    return (finding.get("rule_id", ""), finding.get("fingerprint", ""))


def _validate_key(finding: dict, label: str, lineno: int) -> bool:
    """
    Warn if a finding is missing rule_id or fingerprint.
    Returns True if the finding has a usable key, False otherwise.
    """
    rule_id = finding.get("rule_id", "")
    fingerprint = finding.get("fingerprint", "")
    if not rule_id or not fingerprint:
        missing = []
        if not rule_id:
            missing.append("rule_id")
        if not fingerprint:
            missing.append("fingerprint")
        print(
            f"baseline: WARNING: {label} finding (index {lineno}) missing "
            f"{', '.join(missing)}; skipped in matching",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify audit findings as new/existing/resolved vs a baseline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--current",
        required=True,
        metavar="PATH",
        help="Current findings.jsonl (merge-findings output).",
    )
    parser.add_argument(
        "--baseline",
        required=True,
        metavar="FILE",
        help=(
            "Baseline findings.jsonl to compare against. Must be a file path. "
            "To compare against a git ref, extract the file first: "
            "git show <ref>:.audit/current/findings.jsonl > baseline.jsonl"
        ),
    )
    parser.add_argument(
        "--new-only",
        action="store_true",
        default=False,
        help="Output only findings tagged 'new' (plus the summary). Omits 'existing' and resolved.",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write output JSONL to this file instead of stdout.",
    )
    parser.add_argument(
        "--save-baseline",
        default=None,
        metavar="PATH",
        help=(
            "Copy --current to this path after classification. "
            "Useful for persisting the current run as the next baseline."
        ),
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load both JSONL files
    # ------------------------------------------------------------------
    current_meta, current_findings = _load_jsonl(args.current, "--current")
    _baseline_meta, baseline_findings = _load_jsonl(args.baseline, "--baseline")

    # ------------------------------------------------------------------
    # Build the baseline key set
    # ------------------------------------------------------------------
    baseline_keys: set = set()
    for idx, f in enumerate(baseline_findings):
        if _validate_key(f, "--baseline", idx):
            baseline_keys.add(_match_key(f))

    # ------------------------------------------------------------------
    # Classify current findings
    # ------------------------------------------------------------------
    new_count = 0
    existing_count = 0
    tagged_findings = []

    for idx, f in enumerate(current_findings):
        if not _validate_key(f, "--current", idx):
            # Emit unclassified findings unchanged rather than dropping them.
            tagged_findings.append(f)
            continue

        key = _match_key(f)
        if key in baseline_keys:
            status = "existing"
            existing_count += 1
        else:
            status = "new"
            new_count += 1

        # Tag in properties.baseline_status — do not mutate the original dict.
        tagged = dict(f)
        props = dict(tagged.get("properties") or {})
        props["baseline_status"] = status
        tagged["properties"] = props
        tagged_findings.append(tagged)

    # ------------------------------------------------------------------
    # Compute resolved: baseline keys absent from current
    # ------------------------------------------------------------------
    current_keys: set = set()
    for f in current_findings:
        if f.get("rule_id") and f.get("fingerprint"):
            current_keys.add(_match_key(f))

    # Build resolved records from baseline findings in baseline order.
    resolved_records = []
    seen_resolved_keys: set = set()
    for f in baseline_findings:
        key = _match_key(f)
        if not key[0] or not key[1]:
            continue
        if key not in current_keys and key not in seen_resolved_keys:
            seen_resolved_keys.add(key)
            resolved_records.append({
                "type": "resolved",
                "rule_id": key[0],
                "fingerprint": key[1],
                "baseline": args.baseline,
            })

    resolved_count = len(resolved_records)

    # ------------------------------------------------------------------
    # Build summary record
    # ------------------------------------------------------------------
    summary = {
        "type": "baseline_summary",
        "new": new_count,
        "existing": existing_count,
        "resolved": resolved_count,
        "baseline": args.baseline,
    }

    # ------------------------------------------------------------------
    # Build output lines
    # ------------------------------------------------------------------
    output_lines = []

    # 1. Summary first
    output_lines.append(json.dumps(summary, separators=(",", ":")))

    # 2. Metadata records from current (provenance, coverage_gap, etc.)
    for rec in current_meta:
        output_lines.append(json.dumps(rec, separators=(",", ":")))

    # 3. Tagged findings — all, or new-only
    for f in tagged_findings:
        if args.new_only:
            status = (f.get("properties") or {}).get("baseline_status")
            if status == "existing":
                continue
        output_lines.append(json.dumps(f, separators=(",", ":")))

    # 4. Resolved records (omit when --new-only)
    if not args.new_only:
        for rec in resolved_records:
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
            print(
                f"baseline: ERROR: cannot write output '{args.output}': {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"baseline: wrote {new_count} new, {existing_count} existing, "
            f"{resolved_count} resolved finding(s) to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)

    # ------------------------------------------------------------------
    # Save baseline copy if requested
    # ------------------------------------------------------------------
    if args.save_baseline:
        save_path = Path(args.save_baseline)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(args.current, str(save_path))
        except OSError as exc:
            print(
                f"baseline: ERROR: cannot save baseline to '{args.save_baseline}': {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"baseline: saved current findings as next baseline to {args.save_baseline}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
