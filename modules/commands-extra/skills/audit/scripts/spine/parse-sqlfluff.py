#!/usr/bin/env python3
"""
CCGM audit spine -- parse sqlfluff JSON output -> finding.schema.json JSONL.

Usage: parse-sqlfluff.py <sqlfluff_json_file> <repo_root>

Assumed sqlfluff lint --format json output shape (documented in wrap-sqlfluff.sh):

  [
    {
      "filepath": "db/migrations/0001_create_users.sql",
      "violations": [
        {
          "start_line_no": 5,
          "start_line_pos": 1,
          "end_line_no": 5,
          "end_line_pos": 40,
          "description": "Found SECURITY DEFINER in function definition.",
          "name": "ST07",
          "warning": false,
          "fixable": false
        }
      ]
    }
  ]

The top-level is a JSON array of file objects. Each file object has a "violations"
array. Each violation contains start_line_no (1-based integer), description (string),
and name (rule code string). The "warning" bool controls severity: false -> medium,
true -> low.

check_id assignment:
  - description contains "SECURITY DEFINER" (case-insensitive) -> dm/security-definer-function
  - all others -> dm/sqlfluff-violation

properties.tool is always set to "sqlfluff".
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


# Pattern to detect SECURITY DEFINER descriptions
_SECURITY_DEFINER_RE = re.compile(r"security[\s_-]*definer", re.IGNORECASE)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-sqlfluff.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    if not isinstance(data, list):
        sys.stderr.write("Expected JSON array from sqlfluff lint --format json\n")
        sys.exit(0)

    for file_entry in data:
        if not isinstance(file_entry, dict):
            continue

        file_path = file_entry.get("filepath", "unknown.sql")
        # Make path repo-relative
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        violations = file_entry.get("violations", [])
        if not isinstance(violations, list):
            continue

        for violation in violations:
            if not isinstance(violation, dict):
                continue

            rule_name = violation.get("name", "unknown")
            description = violation.get("description", "sqlfluff violation")
            is_warning = bool(violation.get("warning", False))
            line_no = max(1, int(violation.get("start_line_no", 1)))

            # Determine check_id
            if _SECURITY_DEFINER_RE.search(description):
                check_id = "dm/security-definer-function"
                severity = "medium"
                confidence = "high"
            else:
                check_id = "dm/sqlfluff-violation"
                severity = "low" if is_warning else "medium"
                confidence = "high"

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}".format(file_path, line_no, rule_name)
            )

            finding = normalize.make_finding(
                check_id=check_id,
                rule_id="sqlfluff/{0}".format(rule_name),
                severity=severity,
                confidence=confidence,
                path=file_path,
                line=line_no,
                message=description,
                fingerprint=fp,
                properties={"tool": "sqlfluff"},
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
