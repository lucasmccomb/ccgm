#!/usr/bin/env python3
"""
CCGM audit spine -- parse zizmor SARIF JSON -> finding.schema.json JSONL.

Usage: parse-zizmor.py <zizmor_sarif_json> <repo_root>

# -------------------------------------------------------------------------
# Assumed zizmor --format sarif output shape (documented; not installed locally)
#
# zizmor emits a SARIF 2.1.0 document.  Representative structure:
#
#   {
#     "$schema": "https://...",
#     "version": "2.1.0",
#     "runs": [
#       {
#         "tool": {
#           "driver": {
#             "name": "zizmor",
#             "rules": [
#               {
#                 "id": "excessive-permissions",
#                 "name": "excessive-permissions",
#                 "shortDescription": { "text": "Overbroad GITHUB_TOKEN permissions" },
#                 "defaultConfiguration": { "level": "warning" }
#               }
#             ]
#           }
#         },
#         "results": [
#           {
#             "ruleId": "excessive-permissions",
#             "level": "warning",
#             "message": { "text": "Job 'build' has excessive permissions: write-all" },
#             "locations": [
#               {
#                 "physicalLocation": {
#                   "artifactLocation": { "uri": ".github/workflows/ci.yml", "uriBaseId": "%SRCROOT%" },
#                   "region": { "startLine": 12, "startColumn": 1 }
#                 }
#               }
#             ],
#             "partialFingerprints": {
#               "primaryLocationLineHash": "abc123def456"
#             }
#           }
#         ]
#       }
#     ]
#   }
#
# Known zizmor rule IDs (from source / docs as of 2024-2025):
#   - dangerous-triggers          -> cicd/dangerous-trigger (critical/high)
#   - excessive-permissions       -> cicd/excessive-permissions (medium/high)
#   - template-injection          -> cicd/script-injection (high)
#   - expression-injection        -> cicd/script-injection (high)
#   - artipacked                  -> cicd/excessive-permissions (medium)
#   - pull-request-target         -> cicd/dangerous-trigger (critical)
#   - unpinned-uses               -> cicd/unpinned-action (high)
#   - (any other)                 -> cicd/workflow-security-issue (medium, fallback)
#
# Level mapping:  error -> high, warning -> medium, note/none -> low
# -------------------------------------------------------------------------
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


# Mapping from zizmor rule-id (lower-case) to (check_id, severity).
# Matched by prefix/substring so "template-injection" and "expression-injection"
# both land on cicd/script-injection.
_RULE_MAP = {
    "dangerous-triggers":   ("cicd/dangerous-trigger",    "critical"),
    "pull-request-target":  ("cicd/dangerous-trigger",    "critical"),
    "template-injection":   ("cicd/script-injection",     "high"),
    "expression-injection": ("cicd/script-injection",     "high"),
    "excessive-permissions":("cicd/excessive-permissions", "medium"),
    "artipacked":           ("cicd/excessive-permissions", "medium"),
    "unpinned-uses":        ("cicd/unpinned-action",       "high"),
}

_LEVEL_TO_SEVERITY = {
    "error":   "high",
    "warning": "medium",
    "note":    "low",
    "none":    "low",
}


def _map_rule(rule_id_raw):
    """Return (check_id, severity) for a raw zizmor rule ID."""
    rule_lower = rule_id_raw.lower()
    for key, val in _RULE_MAP.items():
        if key in rule_lower:
            return val
    return ("cicd/workflow-security-issue", "medium")


def process_zizmor_sarif(data, repo_root):
    """
    Parse a SARIF document emitted by 'zizmor --format sarif' and emit
    normalized findings to stdout.
    """
    if not isinstance(data, dict):
        return

    for run in data.get("runs", []):
        if not isinstance(run, dict):
            continue

        for result in run.get("results", []):
            if not isinstance(result, dict):
                continue

            rule_id_raw = result.get("ruleId", "unknown")
            check_id, default_severity = _map_rule(rule_id_raw)

            # Level may override the default severity mapping
            level = result.get("level", "warning").lower()
            severity = _LEVEL_TO_SEVERITY.get(level, "medium")
            # critical is not a SARIF level; only override when not already critical
            if default_severity == "critical":
                severity = "critical"
            elif default_severity == "high" and severity == "medium":
                severity = "high"

            message_obj = result.get("message", {})
            if isinstance(message_obj, dict):
                message = message_obj.get("text", "zizmor finding")
            else:
                message = str(message_obj) if message_obj else "zizmor finding"

            locations = result.get("locations", [{}])
            loc = locations[0] if locations else {}
            pl = loc.get("physicalLocation", {})
            art = pl.get("artifactLocation", {})
            region = pl.get("region", {})

            file_path = art.get("uri", ".github/workflows/unknown.yml")
            # Strip uriBaseId markers like "%SRCROOT%/" that SARIF tools emit
            if file_path.startswith("%SRCROOT%/"):
                file_path = file_path[len("%SRCROOT%/"):]
            # Strip absolute repo prefix if present
            if file_path.startswith(repo_root + "/"):
                file_path = file_path[len(repo_root) + 1:]

            line_no = max(1, int(region.get("startLine", 1)))

            # Prefer tool-supplied fingerprint when schema-valid;
            # fingerprint_from_tool returns None for invalid values.
            fps = result.get("partialFingerprints", {})
            tool_fp = fps.get("primaryLocationLineHash", "")
            fp = None
            if tool_fp:
                fp = normalize.fingerprint_from_tool(tool_fp)
            if fp is None:
                fp = normalize.make_content_fingerprint(
                    "{0}:{1}:{2}".format(file_path, line_no, rule_id_raw)
                )

            finding = normalize.make_finding(
                check_id=check_id,
                rule_id="zizmor/{0}".format(rule_id_raw),
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
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-zizmor.py <zizmor_sarif_json> <repo_root>\n")
        sys.exit(1)

    sarif_file = argv[1]
    repo_root = argv[2].rstrip("/")

    if not os.path.isfile(sarif_file) or os.path.getsize(sarif_file) == 0:
        # No output from zizmor (no findings) -- emit nothing
        return

    try:
        with open(sarif_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        process_zizmor_sarif(data, repo_root)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse zizmor output: {0}\n".format(exc))


if __name__ == "__main__":
    main(sys.argv)
