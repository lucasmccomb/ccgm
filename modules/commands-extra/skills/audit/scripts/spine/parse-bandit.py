#!/usr/bin/env python3
"""
CCGM audit spine -- parse bandit JSON output -> finding.schema.json JSONL.

Usage: parse-bandit.py <bandit_json_file> <repo_root>

Bandit JSON shape:
  {
    "results": [
      {
        "test_id": "B102",
        "test_name": "exec_used",
        "issue_severity": "MEDIUM",
        "issue_confidence": "HIGH",
        "issue_text": "Use of exec detected.",
        "filename": "/abs/path/to/file.py",
        "line_number": 10,
        "line_range": [10, 11],
        "code": "exec(user_input)"
      }
    ]
  }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "UNDEFINED": "info",
}

_CONFIDENCE_MAP = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "UNDEFINED": "low",
}


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-bandit.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    results = data.get("results", [])

    for item in results:
        if not isinstance(item, dict):
            continue

        test_id = item.get("test_id", "B000")
        test_name = item.get("test_name", "unknown")
        sev_raw = item.get("issue_severity", "MEDIUM")
        conf_raw = item.get("issue_confidence", "MEDIUM")
        message = item.get("issue_text", "Bandit finding")
        file_path = item.get("filename", "")
        line_no = max(1, int(item.get("line_number", 1)))
        line_range = item.get("line_range", [])
        code_snippet = item.get("code", "")

        # Make path repo-relative
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        end_line = None
        if line_range and len(line_range) >= 2:
            end_candidate = int(line_range[-1])
            if end_candidate >= line_no:
                end_line = end_candidate

        severity = _SEVERITY_MAP.get(sev_raw.upper(), "medium")
        confidence = _CONFIDENCE_MAP.get(conf_raw.upper(), "medium")

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}:{3}".format(file_path, line_no, test_id, code_snippet[:64])
        )

        finding = normalize.make_finding(
            check_id="sast/{0}".format(test_name.lower().replace("_", "-")),
            rule_id=test_id,
            severity=severity,
            confidence=confidence,
            path=file_path,
            line=line_no,
            message=message,
            fingerprint=fp,
            end_line=end_line,
            properties={"tool": "bandit"},
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
