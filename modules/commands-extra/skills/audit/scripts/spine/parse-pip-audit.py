#!/usr/bin/env python3
"""
CCGM audit spine -- parse pip-audit JSON output -> finding.schema.json JSONL.

Usage: parse-pip-audit.py <pip_audit_json_file>

pip-audit --format json emits a single JSON object.

Assumed output shape (pip-audit >= 2.0):
  {
    "dependencies": [
      {
        "name": "cryptography",
        "version": "38.0.0",
        "vulns": [
          {
            "id": "PYSEC-2023-123",
            "fix_versions": ["41.0.0"],
            "aliases": ["CVE-2023-12345"],
            "description": "A buffer overflow vulnerability..."
          }
        ]
      }
    ]
  }

Packages with an empty "vulns" list are not vulnerable and are skipped.
The "aliases" field may contain CVE IDs; the first CVE alias (if any) is
appended to the message for human reference.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("Usage: parse-pip-audit.py <json_file>\n")
        sys.exit(1)

    json_file = argv[1]

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError as exc:
        sys.stderr.write("Cannot read {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    if not raw:
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write("Invalid JSON from pip-audit: {0}\n".format(exc))
        sys.exit(0)

    if not isinstance(data, dict):
        sys.stderr.write("Unexpected pip-audit output shape (not a dict)\n")
        sys.exit(0)

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list):
        return

    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
        vulns = dep.get("vulns", [])
        if not vulns:
            continue

        pkg_name = dep.get("name", "unknown")
        pkg_version = dep.get("version", "")

        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue

            vuln_id = vuln.get("id", "unknown")
            description = vuln.get("description", "Vulnerable dependency")
            fix_versions = vuln.get("fix_versions", [])
            aliases = vuln.get("aliases", [])

            # Find first CVE alias for human reference
            cve = ""
            for alias in aliases:
                if isinstance(alias, str) and alias.upper().startswith("CVE-"):
                    cve = alias
                    break

            fix_note = ""
            if fix_versions:
                fix_note = " (fix: {0})".format(", ".join(str(v) for v in fix_versions))

            message = "{0} in {1} {2}{3}".format(
                description, pkg_name, pkg_version, fix_note
            ).strip()
            if cve:
                message = "{0} [{1}]".format(message, cve)

            fp = normalize.make_content_fingerprint(
                "{0}:{1}:{2}".format(vuln_id, pkg_name, pkg_version)
            )

            finding = normalize.make_finding(
                check_id="deps/vulnerable-dependency",
                rule_id=vuln_id,
                severity="high",
                confidence="high",
                path="requirements.txt",
                line=1,
                message=message,
                fingerprint=fp,
                properties={
                    "tool": "pip-audit",
                    "package": pkg_name,
                    "ecosystem": "python",
                },
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
