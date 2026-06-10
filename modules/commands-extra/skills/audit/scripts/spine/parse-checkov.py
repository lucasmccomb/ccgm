#!/usr/bin/env python3
"""
CCGM audit spine -- parse checkov JSON output -> finding.schema.json JSONL.

Usage: parse-checkov.py <checkov_json_file> <repo_root>

checkov --output json emits one of two shapes:

  Single-framework output (most common):
    {
      "check_type": "terraform",
      "results": {
        "failed_checks": [
          {
            "check_id": "CKV_AWS_20",
            "check_name": "Ensure the S3 bucket has access control list (ACL) is private",
            "file_path": "/main.tf",
            "file_line_range": [1, 10],
            "resource": "aws_s3_bucket.example",
            "check_class": "...",
            ...
          },
          ...
        ],
        "passed_checks": [...],
        "skipped_checks": [...]
      }
    }

  Multi-framework output (when multiple IaC types are present):
    [
      { "check_type": "terraform", "results": { "failed_checks": [...] } },
      { "check_type": "dockerfile", "results": { "failed_checks": [...] } },
      ...
    ]

  NOTE: We only process failed_checks. Passed and skipped checks are ignored.
  The check_id field (e.g. "CKV_AWS_20") is used as the rule_id. All findings
  are emitted under the "iac/" check_id namespace.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


# ---------------------------------------------------------------------------
# Severity mapping: checkov does not emit severity in standard JSON output,
# so we assign "medium" by default.  Known high-severity check IDs override.
# ---------------------------------------------------------------------------

_HIGH_SEVERITY_PREFIXES = {
    "CKV_AWS_20",   # S3 bucket public
    "CKV_AWS_21",   # S3 versioning
    "CKV_AWS_54",   # S3 public access block
    "CKV_AWS_55",   # S3 public access block (account level)
    "CKV_AWS_18",   # CloudTrail logging
    "CKV_AWS_19",   # CloudTrail encryption
    "CKV_AWS_7",    # KMS key rotation
    "CKV_SECRET",   # Secrets in IaC
    "CKV2_SECRET",  # Secrets in IaC (v2)
}


def _severity_for(check_id):
    """Assign severity based on check_id prefix heuristic."""
    if check_id in _HIGH_SEVERITY_PREFIXES:
        return "high"
    check_upper = check_id.upper()
    if "SECRET" in check_upper or "CREDENTIAL" in check_upper or "KEY" in check_upper:
        return "high"
    # Public ingress / open to 0.0.0.0
    if "PUBLIC" in check_upper or "OPEN" in check_upper or "INGRESS" in check_upper:
        return "high"
    # Encryption misses
    if "ENCRYPT" in check_upper:
        return "medium"
    return "medium"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_failed_checks(failed_checks, repo_root):
    """Yield normalized findings from a failed_checks list."""
    if not isinstance(failed_checks, list):
        return

    for item in failed_checks:
        if not isinstance(item, dict):
            continue

        check_id = item.get("check_id", "CKV_UNKNOWN")
        check_name = item.get("check_name", "checkov finding")
        file_path = item.get("file_path", "")
        resource = item.get("resource", "")

        # Normalize file path: strip leading / and repo_root prefix
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]
        elif file_path.startswith("/"):
            file_path = file_path.lstrip("/")

        if not file_path:
            file_path = "."

        # Extract line number from file_line_range: [start, end]
        line_range = item.get("file_line_range", [1, 1])
        if isinstance(line_range, list) and len(line_range) >= 1:
            try:
                line_no = max(1, int(line_range[0]))
                end_line = max(line_no, int(line_range[1])) if len(line_range) >= 2 else None
            except (TypeError, ValueError):
                line_no = 1
                end_line = None
        else:
            line_no = 1
            end_line = None

        severity = _severity_for(check_id)

        message = check_name
        if resource:
            message = "{0} [{1}]".format(check_name, resource)

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(file_path, line_no, check_id)
        )

        finding = normalize.make_finding(
            check_id="iac/checkov-violation",
            rule_id=check_id,
            severity=severity,
            confidence="medium",
            path=file_path,
            line=line_no,
            message=message,
            fingerprint=fp,
            end_line=end_line,
            properties={"tool": "checkov"},
        )
        normalize.emit_finding(finding)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-checkov.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    # Normalize to a list of framework result objects
    if isinstance(data, dict):
        # Single-framework output
        framework_results = [data]
    elif isinstance(data, list):
        # Multi-framework output
        framework_results = data
    else:
        sys.stderr.write("Unexpected checkov output shape\n")
        sys.exit(0)

    for fw_result in framework_results:
        if not isinstance(fw_result, dict):
            continue
        results = fw_result.get("results", {})
        if not isinstance(results, dict):
            continue
        failed_checks = results.get("failed_checks", [])
        _parse_failed_checks(failed_checks, repo_root)


if __name__ == "__main__":
    main(sys.argv)
