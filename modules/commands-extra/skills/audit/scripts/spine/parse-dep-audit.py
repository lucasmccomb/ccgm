#!/usr/bin/env python3
"""
CCGM audit spine -- parse npm/pnpm/yarn/bun audit JSON -> finding.schema.json JSONL.

Usage: parse-dep-audit.py <audit_json_file> <package_manager>

Handles npm v7+ (advisories object), pnpm (similar to npm), yarn v1 (advisory lines),
and falls back gracefully on unknown shapes.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "moderate": "medium",
    "medium": "medium",
    "low": "low",
    "info": "info",
}


def map_severity(raw):
    if isinstance(raw, str):
        return _SEVERITY_MAP.get(raw.lower(), "medium")
    return "medium"


def process_npm_pnpm(data, pm):
    """npm v7+ / pnpm audit --json format."""
    vulns = data.get("vulnerabilities", {})
    if not vulns and "advisories" in data:
        # npm v6 format
        vulns = data["advisories"]

    for pkg_name, vuln in vulns.items():
        if not isinstance(vuln, dict):
            continue

        # npm v7: severity on the vuln object
        severity_raw = vuln.get("severity", "medium")
        severity = map_severity(severity_raw)

        via = vuln.get("via", [])
        # Extract advisory detail if via contains objects
        advisory = None
        for v in via:
            if isinstance(v, dict):
                advisory = v
                break

        if advisory:
            rule_id = "GHSA-{0}".format(advisory.get("source", pkg_name)) if advisory.get("source") else pkg_name
            cve = advisory.get("cve", "")
            title = advisory.get("title", "Vulnerable dependency")
            url = advisory.get("url", "")
            severity = map_severity(advisory.get("severity", severity_raw))
        else:
            rule_id = pkg_name
            cve = ""
            title = "Vulnerable dependency: {0}".format(pkg_name)
            url = ""

        range_affected = vuln.get("range", "")
        message = "{0} in {1} {2}".format(title, pkg_name, range_affected).strip()
        if cve:
            message = "{0} [{1}]".format(message, cve)
        if url:
            message = "{0} -- {1}".format(message, url)

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(pkg_name, rule_id, range_affected)
        )

        finding = normalize.make_finding(
            check_id="deps/vulnerable-dependency",
            rule_id=rule_id,
            severity=severity,
            confidence="high",
            path="package.json",
            line=1,
            message=message,
            fingerprint=fp,
            properties={
                "tool": "dep-audit",
                "package_manager": pm,
                "package": pkg_name,
            },
        )
        normalize.emit_finding(finding)


def process_yarn(data):
    """yarn audit --json emits NDJSON (one object per line, not an array)."""
    # The input file may already be parsed if it was valid JSON array,
    # or may be a single advisory dict.
    advisories = []
    if isinstance(data, dict) and "data" in data:
        # yarn v1 wraps in {type: "auditAdvisory", data: {...}}
        inner = data.get("data", {})
        adv = inner.get("advisory", {})
        if adv:
            advisories.append(adv)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                inner = item.get("data", {})
                adv = inner.get("advisory", {})
                if adv:
                    advisories.append(adv)

    for advisory in advisories:
        pkg = advisory.get("module_name", "unknown")
        severity = map_severity(advisory.get("severity", "medium"))
        title = advisory.get("title", "Vulnerable dependency")
        cves = advisory.get("cves", [])
        cve = cves[0] if cves else ""
        url = advisory.get("url", "")
        findings = advisory.get("findings", [{}])
        version = findings[0].get("version", "") if findings else ""

        message = "{0} in {1} {2}".format(title, pkg, version).strip()
        if cve:
            message = "{0} [{1}]".format(message, cve)
        if url:
            message = "{0} -- {1}".format(message, url)

        fp = normalize.make_content_fingerprint(
            "{0}:{1}:{2}".format(pkg, title, version)
        )

        finding = normalize.make_finding(
            check_id="deps/vulnerable-dependency",
            rule_id=advisory.get("id", pkg),
            severity=severity,
            confidence="high",
            path="package.json",
            line=1,
            message=message,
            fingerprint=fp,
            properties={
                "tool": "dep-audit",
                "package_manager": "yarn",
                "package": pkg,
            },
        )
        normalize.emit_finding(finding)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-dep-audit.py <json_file> <pm>\n")
        sys.exit(1)

    json_file = argv[1]
    pm = argv[2]

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError as exc:
        sys.stderr.write("Cannot read {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    if not raw:
        return

    # yarn emits NDJSON -- try to parse as array of lines
    if pm == "yarn":
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        parsed_lines = []
        for line in lines:
            try:
                parsed_lines.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if parsed_lines:
            process_yarn(parsed_lines)
            return
        # Fall through to try standard JSON

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write("Invalid JSON from {0} audit: {1}\n".format(pm, exc))
        sys.exit(0)

    if pm in ("npm", "pnpm"):
        process_npm_pnpm(data, pm)
    elif pm == "yarn":
        process_yarn(data)
    elif pm == "bun":
        # bun audit output is not standardized yet; parse best-effort as npm shape
        process_npm_pnpm(data, pm)


if __name__ == "__main__":
    main(sys.argv)
