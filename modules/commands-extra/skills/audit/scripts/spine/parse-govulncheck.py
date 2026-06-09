#!/usr/bin/env python3
"""
CCGM audit spine -- parse govulncheck JSON output -> finding.schema.json JSONL.

Usage: parse-govulncheck.py <govulncheck_json_file>

govulncheck -json emits NDJSON (one object per line).
Objects have type "osv", "finding", "progress", "message".
We care about "finding" objects.

Finding shape:
  {
    "finding": {
      "osv": "GO-2023-1234",
      "fixed_version": "v1.2.3",
      "trace": [
        {
          "module": "golang.org/x/net",
          "version": "v0.1.0",
          "package": "golang.org/x/net/http2",
          "function": "...",
          "position": {"filename": "src/main.go", "line": 10, "column": 1}
        }
      ]
    }
  }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("Usage: parse-govulncheck.py <json_file>\n")
        sys.exit(1)

    json_file = argv[1]

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        sys.stderr.write("Cannot read {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(obj, dict):
            continue

        finding_data = obj.get("finding")
        if not finding_data:
            continue

        osv_id = finding_data.get("osv", "unknown")
        trace = finding_data.get("trace", [])

        # Use the first trace entry for location
        module = ""
        version = ""
        file_path = "go.mod"
        line_no = 1

        if trace:
            first = trace[0]
            module = first.get("module", "")
            version = first.get("version", "")
            pos = first.get("position")
            if pos and isinstance(pos, dict):
                file_path = pos.get("filename", "go.mod") or "go.mod"
                line_no = max(1, int(pos.get("line", 1)))

        message = "Go vulnerability {0} in {1} {2}".format(osv_id, module, version).strip()
        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(osv_id, module, version)
        )

        finding = normalize.make_finding(
            check_id="deps/go-vulnerability",
            rule_id=osv_id,
            severity="high",
            confidence="high",
            path=file_path,
            line=line_no,
            message=message,
            fingerprint=fp,
            properties={
                "tool": "govulncheck",
                "package": module,
            },
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
