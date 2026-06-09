#!/usr/bin/env python3
"""
CCGM audit spine -- parse hadolint JSON output -> finding.schema.json JSONL.

Usage: parse-hadolint.py <hadolint_json_file> <repo_root>

hadolint --format json emits a JSON array:
  [
    {
      "file": "/abs/path/Dockerfile",
      "line": 3,
      "column": 1,
      "level": "warning",
      "code": "DL3008",
      "message": "Pin versions in apt get install."
    }
  ]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "error": "high",
    "warning": "medium",
    "info": "low",
    "style": "info",
}


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-hadolint.py <json_file> <repo_root>\n")
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
        sys.stderr.write("Expected JSON array from hadolint\n")
        sys.exit(0)

    for item in data:
        if not isinstance(item, dict):
            continue

        file_path = item.get("file", "Dockerfile")
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        line_no = max(1, int(item.get("line", 1)))
        level = item.get("level", "warning")
        code = item.get("code", "DL0000")
        message = item.get("message", "hadolint finding")

        severity = _SEVERITY_MAP.get(level.lower(), "medium")

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(file_path, line_no, code)
        )

        finding = normalize.make_finding(
            check_id="iac/dockerfile-issue",
            rule_id=code,
            severity=severity,
            confidence="high",
            path=file_path,
            line=line_no,
            message=message,
            fingerprint=fp,
            properties={"tool": "hadolint"},
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
