#!/usr/bin/env python3
"""
CCGM audit spine -- parse squawk JSON output -> finding.schema.json JSONL.

Usage: parse-squawk.py <squawk_json_file> <repo_root>

Assumed squawk --reporter json output shape (documented in wrap-squawk.sh):

  [
    {
      "file": "db/migrations/0001_create_users.sql",
      "violations": [
        {
          "rule": "require-concurrent-index-creation",
          "level": "Warning",
          "messages": [
            {
              "Note": "Use CONCURRENTLY when creating indexes to avoid locking the table."
            }
          ],
          "position": {
            "start": { "line": 5, "col": 1 },
            "end":   { "line": 5, "col": 40 }
          }
        }
      ]
    }
  ]

The top-level array has one entry per file. Each entry has a "violations" array.
Each violation has:
  - rule:     string — squawk rule name, e.g. "require-concurrent-index-creation"
  - level:    string — "Warning" | "Error" | "Note"
  - messages: list of single-key objects, e.g. [{"Note": "..."}, {"Help": "..."}]
  - position: object with start/end, each containing line (1-based) and col

squawk rule -> dm/* check_id mapping:
  require-concurrent-index-creation  -> dm/index-without-concurrently
  ban-drop-database                  -> dm/squawk-violation
  prefer-robust-stmts                -> dm/squawk-violation
  add-field-with-default             -> dm/squawk-violation
  (all others)                       -> dm/squawk-violation
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


# Severity mapping from squawk level strings.
_SEVERITY_MAP = {
    "error": "high",
    "warning": "medium",
    "note": "low",
}

# Rule-to-check_id mapping; unrecognised rules fall back to dm/squawk-violation.
_RULE_CHECK_ID = {
    "require-concurrent-index-creation": "dm/index-without-concurrently",
}
_DEFAULT_CHECK_ID = "dm/squawk-violation"


def _extract_message(messages):
    """
    Extract a human-readable message string from squawk's messages list.
    Each element is a single-key dict: {"Note": "..."} or {"Help": "..."}.
    Returns the first Note or Help value found, or "squawk violation" as default.
    """
    if not isinstance(messages, list):
        return "squawk violation"
    for msg_obj in messages:
        if not isinstance(msg_obj, dict):
            continue
        for key in ("Note", "Help", "Error"):
            val = msg_obj.get(key)
            if val:
                return str(val)
    return "squawk violation"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-squawk.py <json_file> <repo_root>\n")
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
        sys.stderr.write("Expected JSON array from squawk --reporter json\n")
        sys.exit(0)

    for file_entry in data:
        if not isinstance(file_entry, dict):
            continue

        file_path = file_entry.get("file", "unknown.sql")
        # Make path repo-relative
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        violations = file_entry.get("violations", [])
        if not isinstance(violations, list):
            continue

        for violation in violations:
            if not isinstance(violation, dict):
                continue

            rule = violation.get("rule", "unknown")
            level = violation.get("level", "Warning").lower()
            messages = violation.get("messages", [])
            position = violation.get("position", {})
            start = position.get("start", {})
            line_no = max(1, int(start.get("line", 1)))

            check_id = _RULE_CHECK_ID.get(rule, _DEFAULT_CHECK_ID)
            severity = _SEVERITY_MAP.get(level, "medium")
            message = _extract_message(messages)
            if message == "squawk violation":
                message = "squawk rule {0}".format(rule)

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}".format(file_path, line_no, rule)
            )

            finding = normalize.make_finding(
                check_id=check_id,
                rule_id="squawk/{0}".format(rule),
                severity=severity,
                confidence="high",
                path=file_path,
                line=line_no,
                message=message,
                fingerprint=fp,
                properties={"tool": "squawk"},
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
