#!/usr/bin/env python3
"""
CCGM audit spine -- parse actionlint + zizmor JSON -> finding.schema.json JSONL.

Usage: parse-actionlint.py <actionlint_json> <zizmor_json> <repo_root>

actionlint -format '{{json .}}' emits a JSON array:
  [
    {
      "message": "...",
      "filepath": ".github/workflows/ci.yml",
      "line": 10,
      "column": 1,
      "kind": "error",
      "snippet": "...",
      "end_column": 20
    }
  ]

zizmor --format json emits a SARIF-like structure (best-effort parse).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


def process_actionlint(data, repo_root):
    if not isinstance(data, list):
        return

    for item in data:
        if not isinstance(item, dict):
            continue

        file_path = item.get("filepath", ".github/workflows/unknown.yml")
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        line_no = max(1, int(item.get("line", 1)))
        message = item.get("message", "actionlint finding")
        kind = item.get("kind", "error")

        severity = "medium" if kind == "error" else "low"

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(file_path, line_no, message[:64])
        )

        finding = normalize.make_finding(
            check_id="ci/workflow-issue",
            rule_id="actionlint/{0}".format(kind),
            severity=severity,
            confidence="high",
            path=file_path,
            line=line_no,
            message=message,
            fingerprint=fp,
            properties={"tool": "actionlint"},
        )
        normalize.emit_finding(finding)


def process_zizmor(data, repo_root):
    """Parse zizmor output -- handles both SARIF and simple array shapes."""
    if not data:
        return

    # Try SARIF shape first
    runs = data.get("runs", []) if isinstance(data, dict) else []
    for run in runs:
        for result in run.get("results", []):
            if not isinstance(result, dict):
                continue

            rule_id = result.get("ruleId", "zizmor/unknown")
            message_obj = result.get("message", {})
            message = message_obj.get("text", "zizmor finding") if isinstance(message_obj, dict) else str(message_obj)
            sev_raw = result.get("level", "warning")
            severity = "high" if sev_raw == "error" else "medium" if sev_raw == "warning" else "low"

            locations = result.get("locations", [{}])
            loc = locations[0] if locations else {}
            pl = loc.get("physicalLocation", {})
            art = pl.get("artifactLocation", {})
            region = pl.get("region", {})

            file_path = art.get("uri", ".github/workflows/unknown.yml")
            if file_path.startswith(repo_root + "/"):
                file_path = file_path[len(repo_root) + 1:]

            line_no = max(1, int(region.get("startLine", 1)))

            # Use tool fingerprint when schema-valid;
            # fingerprint_from_tool returns None for invalid values.
            fps = result.get("partialFingerprints", {})
            tool_fp = fps.get("primaryLocationLineHash", "")
            fp = None
            if tool_fp:
                fp = normalize.fingerprint_from_tool(tool_fp)
            if fp is None:
                fp = normalize.make_content_fingerprint(
                    "{0}:{1}:{2}".format(file_path, line_no, rule_id)
                )

            finding = normalize.make_finding(
                check_id="ci/workflow-injection",
                rule_id=rule_id,
                severity=severity,
                confidence="high",
                path=file_path,
                line=line_no,
                message=message,
                fingerprint=fp,
                properties={"tool": "zizmor"},
            )
            normalize.emit_finding(finding)


def main(argv):
    if len(argv) < 4:
        sys.stderr.write("Usage: parse-actionlint.py <al_json> <zi_json> <repo_root>\n")
        sys.exit(1)

    al_file = argv[1]
    zi_file = argv[2]
    repo_root = argv[3].rstrip("/")

    # actionlint
    if os.path.isfile(al_file) and os.path.getsize(al_file) > 0:
        try:
            with open(al_file, "r", encoding="utf-8") as fh:
                al_data = json.load(fh)
            process_actionlint(al_data, repo_root)
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write("Cannot parse actionlint output: {0}\n".format(exc))

    # zizmor (optional)
    if os.path.isfile(zi_file) and os.path.getsize(zi_file) > 0:
        try:
            with open(zi_file, "r", encoding="utf-8") as fh:
                zi_data = json.load(fh)
            process_zizmor(zi_data, repo_root)
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write("Cannot parse zizmor output: {0}\n".format(exc))


if __name__ == "__main__":
    main(sys.argv)
