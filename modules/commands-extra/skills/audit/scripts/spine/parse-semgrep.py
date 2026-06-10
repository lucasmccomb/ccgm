#!/usr/bin/env python3
"""
CCGM audit spine -- parse semgrep JSON output -> finding.schema.json JSONL.

Usage: parse-semgrep.py <semgrep_json_file> <repo_root>

Semgrep JSON shape (results array):
  {
    "check_id": "python.lang.security.audit.exec-detected.exec-detected",
    "path": "src/app.py",
    "start": {"line": 10, "col": 1},
    "end": {"line": 10, "col": 50},
    "extra": {
      "message": "Use of exec",
      "severity": "WARNING",
      "metadata": { "confidence": "HIGH" },
      "fingerprint": "abc...",
      "lines": "exec(user_input)"
    }
  }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "info",
    "LOW": "low",
}

_CONFIDENCE_MAP = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}


def map_severity(semgrep_sev):
    return _SEVERITY_MAP.get(semgrep_sev.upper(), "medium")


def map_confidence(meta):
    raw = meta.get("confidence", "MEDIUM")
    if isinstance(raw, str):
        return _CONFIDENCE_MAP.get(raw.upper(), "medium")
    return "medium"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-semgrep.py <json_file> <repo_root>\n")
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
    if not results:
        return

    for item in results:
        if not isinstance(item, dict):
            continue

        rule_id = item.get("check_id", "unknown")
        path = item.get("path", "")
        extra = item.get("extra", {})
        message = extra.get("message", "Semgrep finding")
        sev_raw = extra.get("severity", "WARNING")
        meta = extra.get("metadata", {})
        start = item.get("start", {})
        end_info = item.get("end", {})
        tool_fp = extra.get("fingerprint", "")
        lines_ctx = extra.get("lines", "")

        # Make path repo-relative
        if path.startswith(repo_root + "/"):
            path = path[len(repo_root) + 1:]

        start_line = max(1, int(start.get("line", 1)))
        end_line_raw = int(end_info.get("line", start_line))
        end_line = end_line_raw if end_line_raw >= start_line else None

        severity = map_severity(sev_raw)
        confidence = map_confidence(meta)

        # Fingerprint: use the tool's fingerprint only when it is schema-valid
        # (fingerprint_from_tool returns None for invalid values such as
        # semgrep's 'requires login' placeholder emitted without Semgrep Cloud
        # authentication). Fall back to content-based fingerprint on None.
        fp = None
        if tool_fp:
            fp = normalize.fingerprint_from_tool(tool_fp)
        if fp is None:
            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}:{3}".format(path, start_line, rule_id, lines_ctx)
            )

        # Derive a short check_id from the rule
        # e.g. "python.lang.security.audit.exec-detected" -> "sast/exec-detected"
        parts = rule_id.split(".")
        short = parts[-1] if parts else rule_id
        check_id = "sast/{0}".format(short)

        finding = normalize.make_finding(
            check_id=check_id,
            rule_id=rule_id,
            severity=severity,
            confidence=confidence,
            path=path,
            line=start_line,
            message=message,
            fingerprint=fp,
            end_line=end_line,
            properties={"tool": "semgrep"},
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
