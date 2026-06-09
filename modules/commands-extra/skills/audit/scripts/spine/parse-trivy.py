#!/usr/bin/env python3
"""
CCGM audit spine -- parse trivy JSON output -> finding.schema.json JSONL.

Usage: parse-trivy.py <trivy_json_file> <repo_root>

Trivy JSON shape:
  {
    "Results": [
      {
        "Target": "package-lock.json",
        "Type": "npm",
        "Vulnerabilities": [
          {
            "VulnerabilityID": "CVE-2023-1234",
            "PkgName": "lodash",
            "InstalledVersion": "4.17.19",
            "Severity": "HIGH",
            "Title": "Prototype Pollution",
            "Description": "...",
            "PrimaryURL": "https://..."
          }
        ],
        "Misconfigurations": [
          {
            "ID": "DS002",
            "Title": "Image user should not be 'root'",
            "Severity": "HIGH",
            "Message": "...",
            "CauseMetadata": {"StartLine": 5, "EndLine": 7}
          }
        ]
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
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "UNKNOWN": "info",
    "INFORMATIONAL": "info",
}


def map_severity(raw):
    if isinstance(raw, str):
        return _SEVERITY_MAP.get(raw.upper(), "medium")
    return "medium"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-trivy.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    results = data.get("Results", [])

    for result in results:
        if not isinstance(result, dict):
            continue

        target = result.get("Target", "unknown")
        # Make path repo-relative
        if target.startswith(repo_root + "/"):
            target = target[len(repo_root) + 1:]

        # Vulnerabilities
        for vuln in result.get("Vulnerabilities", []) or []:
            if not isinstance(vuln, dict):
                continue

            vuln_id = vuln.get("VulnerabilityID", "CVE-unknown")
            pkg = vuln.get("PkgName", "unknown")
            version = vuln.get("InstalledVersion", "")
            severity = map_severity(vuln.get("Severity", "MEDIUM"))
            title = vuln.get("Title", vuln_id)
            url = vuln.get("PrimaryURL", "")

            message = "{0}: {1} in {2} {3}".format(vuln_id, title, pkg, version).strip()
            if url:
                message = "{0} -- {1}".format(message, url)

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}:{3}".format(target, vuln_id, pkg, version)
            )

            finding = normalize.make_finding(
                check_id="deps/container-vulnerability",
                rule_id=vuln_id,
                severity=severity,
                confidence="high",
                path=target,
                line=1,
                message=message,
                fingerprint=fp,
                properties={
                    "tool": "trivy",
                    "package": pkg,
                },
            )
            normalize.emit_finding(finding)

        # Misconfigurations
        for misconfig in result.get("Misconfigurations", []) or []:
            if not isinstance(misconfig, dict):
                continue

            mc_id = misconfig.get("ID", "MC0000")
            title = misconfig.get("Title", "Misconfiguration")
            severity = map_severity(misconfig.get("Severity", "MEDIUM"))
            message = misconfig.get("Message", title)
            cause = misconfig.get("CauseMetadata", {})
            line_no = max(1, int(cause.get("StartLine", 1))) if cause else 1
            end_line_raw = cause.get("EndLine") if cause else None
            end_line = int(end_line_raw) if end_line_raw and int(end_line_raw) >= line_no else None

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}".format(target, mc_id, line_no)
            )

            finding = normalize.make_finding(
                check_id="iac/misconfig",
                rule_id=mc_id,
                severity=severity,
                confidence="high",
                path=target,
                line=line_no,
                message="{0}: {1}".format(mc_id, message),
                fingerprint=fp,
                end_line=end_line,
                properties={"tool": "trivy"},
            )
            normalize.emit_finding(finding)

        # Secrets
        for secret in result.get("Secrets", []) or []:
            if not isinstance(secret, dict):
                continue

            rule_id = secret.get("RuleID", "secret-unknown")
            title = secret.get("Title", "Secret detected")
            severity = "high"
            start_line = max(1, int(secret.get("StartLine", 1)))
            end_line_raw = secret.get("EndLine")
            end_line = int(end_line_raw) if end_line_raw and int(end_line_raw) >= start_line else None
            match_val = secret.get("Match", "")

            # Redact the matched secret value
            redacted = normalize.redact_secret(match_val) if match_val else "[redacted]"
            message = "{0} [{1}] matched: {2}".format(title, rule_id, redacted)

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}:{3}".format(target, start_line, rule_id, match_val[:8] if match_val else "")
            )

            finding = normalize.make_finding(
                check_id="secrets/leaked-credential",
                rule_id="trivy/{0}".format(rule_id),
                severity=severity,
                confidence="high",
                path=target,
                line=start_line,
                message=message,
                fingerprint=fp,
                end_line=end_line,
                properties={"tool": "trivy"},
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
