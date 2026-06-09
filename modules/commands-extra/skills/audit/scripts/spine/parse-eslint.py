#!/usr/bin/env python3
"""
CCGM audit spine -- parse eslint JSON output -> finding.schema.json JSONL.

Usage: parse-eslint.py <eslint_json_file> <repo_root>

ESLint JSON shape (array of file results):
  [
    {
      "filePath": "/abs/path/to/file.ts",
      "messages": [
        {
          "ruleId": "no-eval",
          "severity": 2,
          "message": "eval can be harmful.",
          "line": 10,
          "endLine": 10,
          "column": 1,
          "endColumn": 20
        }
      ]
    }
  ]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


def map_severity(eslint_sev):
    # ESLint severity: 0=off, 1=warn, 2=error
    if eslint_sev == 2:
        return "medium"
    if eslint_sev == 1:
        return "low"
    return "info"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-eslint.py <json_file> <repo_root>\n")
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
        sys.stderr.write("Expected JSON array from eslint\n")
        sys.exit(0)

    for file_result in data:
        if not isinstance(file_result, dict):
            continue

        file_path = file_result.get("filePath", "")
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        messages = file_result.get("messages", [])
        for msg in messages:
            if not isinstance(msg, dict):
                continue

            rule_id = msg.get("ruleId") or "unknown"
            sev_raw = msg.get("severity", 2)
            message = msg.get("message", "ESLint finding")
            line = max(1, int(msg.get("line", 1)))
            end_line_raw = msg.get("endLine")
            end_line = int(end_line_raw) if end_line_raw and int(end_line_raw) >= line else None

            severity = map_severity(sev_raw)

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}:{3}".format(file_path, line, rule_id, message[:64])
            )

            check_id = "lint/{0}".format(rule_id.replace("/", "-").replace("@", ""))

            finding = normalize.make_finding(
                check_id=check_id,
                rule_id=rule_id,
                severity=severity,
                confidence="high",
                path=file_path,
                line=line,
                message=message,
                fingerprint=fp,
                end_line=end_line,
                properties={"tool": "eslint"},
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
