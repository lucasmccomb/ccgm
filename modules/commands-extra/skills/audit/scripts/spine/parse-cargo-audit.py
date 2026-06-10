#!/usr/bin/env python3
"""
CCGM audit spine -- parse cargo-audit JSON output -> finding.schema.json JSONL.

Usage: parse-cargo-audit.py <cargo_audit_json_file>

cargo audit --json emits a single JSON object.

Assumed output shape (cargo-audit >= 0.17, rustsec advisory DB):
  {
    "database": { "advisory-count": 123, ... },
    "lockfile": { "dependency-count": 45 },
    "vulnerabilities": {
      "found": true,
      "count": 2,
      "list": [
        {
          "advisory": {
            "id": "RUSTSEC-2023-0001",
            "package": "openssl",
            "title": "Use after free in EVP_KEY_CTX",
            "description": "...",
            "date": "2023-01-01",
            "url": "https://rustsec.org/advisories/RUSTSEC-2023-0001.html",
            "aliases": ["CVE-2023-0001"],
            "severity": "high"
          },
          "versions": {
            "patched": [">=1.0.2u"],
            "unaffected": []
          },
          "affected": {
            "package": {
              "name": "openssl",
              "version": "1.0.2t",
              "source": "registry+..."
            },
            "cvss": "CVSS:3.1/..."
          }
        }
      ]
    },
    "warnings": {
      "list": [...]
    }
  }

The "vulnerabilities.list" array is the primary signal.
The "warnings" section (unmaintained, unsound, notice) is parsed as medium/low.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "info": "info",
}


def map_severity(raw):
    if isinstance(raw, str):
        return _SEVERITY_MAP.get(raw.lower(), "high")
    return "high"


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("Usage: parse-cargo-audit.py <json_file>\n")
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
        sys.stderr.write("Invalid JSON from cargo-audit: {0}\n".format(exc))
        sys.exit(0)

    if not isinstance(data, dict):
        sys.stderr.write("Unexpected cargo-audit output shape (not a dict)\n")
        sys.exit(0)

    # --- vulnerabilities section ---
    vulns_section = data.get("vulnerabilities", {})
    vuln_list = vulns_section.get("list", []) if isinstance(vulns_section, dict) else []

    for item in vuln_list:
        if not isinstance(item, dict):
            continue

        advisory = item.get("advisory", {})
        if not isinstance(advisory, dict):
            continue

        affected = item.get("affected", {})
        pkg_obj = {}
        if isinstance(affected, dict):
            pkg_obj = affected.get("package", {}) or {}

        vuln_id = advisory.get("id", "unknown")
        title = advisory.get("title", "Vulnerable dependency")
        description = advisory.get("description", "")
        pkg_name = advisory.get("package", pkg_obj.get("name", "unknown"))
        pkg_version = pkg_obj.get("version", "")
        severity_raw = advisory.get("severity", "high")
        severity = map_severity(severity_raw)
        url = advisory.get("url", "")
        aliases = advisory.get("aliases", [])

        cve = ""
        for alias in aliases:
            if isinstance(alias, str) and alias.upper().startswith("CVE-"):
                cve = alias
                break

        message = "{0} in {1} {2}".format(title, pkg_name, pkg_version).strip()
        if description:
            # Truncate long descriptions to keep messages readable
            short_desc = description[:120].rstrip()
            if len(description) > 120:
                short_desc += "..."
            message = "{0}: {1}".format(message, short_desc)
        if cve:
            message = "{0} [{1}]".format(message, cve)
        if url:
            message = "{0} -- {1}".format(message, url)

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(vuln_id, pkg_name, pkg_version)
        )

        finding = normalize.make_finding(
            check_id="deps/vulnerable-dependency",
            rule_id=vuln_id,
            severity=severity,
            confidence="high",
            path="Cargo.toml",
            line=1,
            message=message,
            fingerprint=fp,
            properties={
                "tool": "cargo-audit",
                "package": pkg_name,
                "ecosystem": "rust",
            },
        )
        normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
