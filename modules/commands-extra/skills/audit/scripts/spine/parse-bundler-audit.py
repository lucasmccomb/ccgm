#!/usr/bin/env python3
"""
CCGM audit spine -- parse bundler-audit output -> finding.schema.json JSONL.

Usage: parse-bundler-audit.py <bundler_audit_output_file>

bundler-audit supports two output formats:

1. JSON format (bundler-audit >= 0.9, --format json):
   {
     "version": "0.9.2",
     "created_at": "2024-01-01T00:00:00Z",
     "results": [
       {
         "type": "InsecureSource",
         "source": { "uri": "http://insecure.example" }
       },
       {
         "type": "UnpatchedGem",
         "gem": {
           "name": "activesupport",
           "version": "5.2.0"
         },
         "advisory": {
           "id": "CVE-2023-12345",
           "ghsa": "GHSA-xxxx-xxxx-xxxx",
           "title": "Possible ReDoS vulnerability...",
           "date": "2023-01-15",
           "url": "https://github.com/advisories/GHSA-xxxx-xxxx-xxxx",
           "description": "...",
           "cvss_v2": 5.0,
           "cvss_v3": 7.5,
           "cve": "2023-12345",
           "osvdb": null,
           "criticality": "high",
           "patched_versions": [">= 6.1.7.3", ">= 7.0.4.3"],
           "unaffected_versions": []
         }
       }
     ],
     "ignored": [],
     "totals": {
       "unpatched": 1,
       "ignored": 0
     }
   }

2. Text format (bundler-audit < 0.9, default output):
   Name: activesupport
   Version: 5.2.0
   Advisory: CVE-2023-12345
   Criticality: High
   URL: https://github.com/advisories/GHSA-xxxx-xxxx-xxxx
   Title: Possible ReDoS vulnerability in GlobalID
   Solution: upgrade to >= 6.1.7.3, >= 7.0.4.3

   Vulnerabilities found!

The parser tries JSON first; on failure, falls back to line-based text parsing.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "none": "low",
    "unknown": "medium",
}


def map_severity(raw):
    if isinstance(raw, str):
        return _SEVERITY_MAP.get(raw.lower(), "high")
    return "high"


def map_severity_from_cvss(cvss_v3, cvss_v2):
    """Derive severity from CVSS score when criticality field is absent."""
    score = cvss_v3 if cvss_v3 is not None else cvss_v2
    if score is None:
        return "high"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def process_json(data):
    """Parse bundler-audit JSON format."""
    results = data.get("results", [])
    if not isinstance(results, list):
        return

    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "UnpatchedGem":
            continue

        gem = item.get("gem", {}) or {}
        advisory = item.get("advisory", {}) or {}

        pkg_name = gem.get("name", "unknown")
        pkg_version = gem.get("version", "")
        vuln_id = advisory.get("id") or advisory.get("cve", "unknown")
        title = advisory.get("title", "Vulnerable gem")
        url = advisory.get("url", "")
        criticality = advisory.get("criticality", "")
        cvss_v3 = advisory.get("cvss_v3")
        cvss_v2 = advisory.get("cvss_v2")

        if criticality:
            severity = map_severity(criticality)
        else:
            severity = map_severity_from_cvss(cvss_v3, cvss_v2)

        message = "{0} in {1} {2}".format(title, pkg_name, pkg_version).strip()
        if url:
            message = "{0} -- {1}".format(message, url)

        # Prefix vuln_id with CVE- if it looks like a bare CVE number
        if re.fullmatch(r"\d{4}-\d+", vuln_id):
            vuln_id = "CVE-{0}".format(vuln_id)

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(vuln_id, pkg_name, pkg_version)
        )

        finding = normalize.make_finding(
            check_id="deps/vulnerable-dependency",
            rule_id=vuln_id,
            severity=severity,
            confidence="high",
            path="Gemfile.lock",
            line=1,
            message=message,
            fingerprint=fp,
            properties={
                "tool": "bundler-audit",
                "package": pkg_name,
                "ecosystem": "ruby",
            },
        )
        normalize.emit_finding(finding)


def process_text(text):
    """Parse bundler-audit text format (line-based key: value blocks)."""
    current = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            if current:
                emit_text_finding(current)
                current = {}
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current[key.strip().lower()] = value.strip()

    if current:
        emit_text_finding(current)


def emit_text_finding(rec):
    """Emit a single finding from a key:value block parsed from text output."""
    name = rec.get("name", "")
    if not name:
        return  # Not a vulnerability block

    version = rec.get("version", "")
    advisory_id = rec.get("advisory", rec.get("cve", "unknown"))
    criticality = rec.get("criticality", "")
    title = rec.get("title", "Vulnerable gem")
    url = rec.get("url", "")

    severity = map_severity(criticality) if criticality else "high"

    message = "{0} in {1} {2}".format(title, name, version).strip()
    if url:
        message = "{0} -- {1}".format(message, url)

    if re.fullmatch(r"\d{4}-\d+", advisory_id):
        advisory_id = "CVE-{0}".format(advisory_id)

    fp = normalize.make_content_fingerprint(
        "{0}:{1}:{2}".format(advisory_id, name, version)
    )

    finding = normalize.make_finding(
        check_id="deps/vulnerable-dependency",
        rule_id=advisory_id,
        severity=severity,
        confidence="high",
        path="Gemfile.lock",
        line=1,
        message=message,
        fingerprint=fp,
        properties={
            "tool": "bundler-audit",
            "package": name,
            "ecosystem": "ruby",
        },
    )
    normalize.emit_finding(finding)


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("Usage: parse-bundler-audit.py <output_file>\n")
        sys.exit(1)

    output_file = argv[1]

    try:
        with open(output_file, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError as exc:
        sys.stderr.write("Cannot read {0}: {1}\n".format(output_file, exc))
        sys.exit(0)

    if not raw:
        return

    # Try JSON first
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "results" in data:
            process_json(data)
            return
    except json.JSONDecodeError:
        pass

    # Fall back to text format
    process_text(raw)


if __name__ == "__main__":
    main(sys.argv)
