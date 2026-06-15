#!/usr/bin/env python3
"""
CCGM audit spine -- parse gitleaks JSON output -> finding.schema.json JSONL.

Usage: parse-gitleaks.py <gitleaks_json_file> <repo_root>

Gitleaks JSON shape (one finding per array element):
  {
    "Description": "Generic API Key",
    "StartLine": 10,
    "EndLine": 10,
    "File": "config/secrets.env",
    "Secret": "AKIAIOSFODNN7EXAMPLE",
    "RuleID": "generic-api-key",
    "Fingerprint": "abc123..."  (may be present)
    ...
  }
"""

import json
import os
import sys

# Allow importing normalize from same directory
sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    # gitleaks rule IDs -> severity (conservative: all secrets are high)
    "default": "high",
}

_RULE_SEVERITY = {
    "generic-api-key": "high",
    "aws-access-token": "critical",
    "github-token": "critical",
    "github-fine-grained-pat": "critical",
    "github-pat": "critical",
    "google-api-key": "high",
    "slack-webhook-url": "high",
    "stripe-access-token": "critical",
    "private-key": "critical",
}


def severity_for_rule(rule_id):
    return _RULE_SEVERITY.get(rule_id, _SEVERITY_MAP["default"])


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-gitleaks.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError as exc:
        sys.stderr.write("Cannot read {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    if not raw or raw in ("null", "[]"):
        # No findings
        return

    try:
        findings_raw = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write("Invalid JSON from gitleaks: {0}\n".format(exc))
        sys.exit(0)

    if not isinstance(findings_raw, list):
        sys.stderr.write("Expected JSON array from gitleaks\n")
        sys.exit(0)

    for item in findings_raw:
        if not isinstance(item, dict):
            continue

        rule_id = item.get("RuleID", "unknown")
        description = item.get("Description", "Secret detected")
        file_path = item.get("File", "")
        start_line = item.get("StartLine", 1)
        end_line = item.get("EndLine")
        secret_val = item.get("Secret", "")
        tool_fp = item.get("Fingerprint", "")

        # Make path repo-relative
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        # Redact the secret value before it enters the message
        redacted = normalize.redact_secret(secret_val) if secret_val else "[redacted]"
        message = "{0} [{1}] matched value: {2}".format(description, rule_id, redacted)

        # Fingerprint: gitleaks emits "filepath:rule:line" as the fingerprint,
        # which can be an absolute path and exceed the 128-char limit in
        # finding.schema.json. We always recompute using make_content_fingerprint
        # so the fingerprint is stable and schema-conformant.
        # (The tool fingerprint is still useful for dedup upstream -- we store
        # the raw tool_fp in properties for that purpose.)
        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}:{3}".format(file_path, start_line, rule_id, secret_val[:8] if secret_val else "")
        )

        # Validate line number
        if not isinstance(start_line, int) or start_line < 1:
            start_line = 1

        end = end_line if (isinstance(end_line, int) and end_line >= start_line) else None

        props = {"tool": "gitleaks"}
        if tool_fp:
            props["tool_fingerprint"] = tool_fp
        finding = normalize.make_finding(
            check_id="secrets/leaked-credential",
            rule_id=rule_id,
            severity=severity_for_rule(rule_id),
            confidence="high",
            path=file_path,
            line=start_line,
            message=message,
            fingerprint=fp,
            end_line=end,
            properties=props,
            # Heuristic secret match -- FP-prone on test fixtures and fabricated
            # keys, so worker triage must be able to dismiss it (#4).
            detection="hybrid",
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
