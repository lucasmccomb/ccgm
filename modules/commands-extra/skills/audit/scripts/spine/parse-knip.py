#!/usr/bin/env python3
"""
CCGM audit spine -- parse knip JSON output -> finding.schema.json JSONL.

Usage: parse-knip.py <knip_json_file> <repo_root>

Knip JSON shape:
  {
    "files": ["src/old.ts"],
    "issues": [
      {
        "file": "src/utils.ts",
        "owners": [],
        "dependencies": [],
        "devDependencies": [],
        "optionalPeerDependencies": [],
        "unlisted": [],
        "unresolved": [],
        "exports": [{"name": "foo", "line": 10, "col": 1, "pos": 100}],
        "types": [],
        "nsExports": [],
        "nsTypes": [],
        "enumMembers": {},
        "classMembers": {},
        "duplicates": []
      }
    ]
  }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-knip.py <json_file> <repo_root>\n")
        sys.exit(1)

    json_file = argv[1]
    repo_root = argv[2].rstrip("/")

    try:
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("Cannot parse {0}: {1}\n".format(json_file, exc))
        sys.exit(0)

    # Unused files
    for file_path in data.get("files", []):
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        fp = normalize.make_content_fingerprint(
            "unused-file:{0}".format(file_path)
        )
        finding = normalize.make_finding(
            check_id="dead-code/unused-file",
            rule_id="knip/unused-file",
            severity="low",
            confidence="medium",
            path=file_path,
            line=1,
            message="Unused file: {0}".format(file_path),
            fingerprint=fp,
            properties={"tool": "knip"},
        )
        normalize.emit_finding(finding)

    # Per-file issues
    for issue in data.get("issues", []):
        if not isinstance(issue, dict):
            continue

        file_path = issue.get("file", "")
        if file_path.startswith(repo_root + "/"):
            file_path = file_path[len(repo_root) + 1:]

        # Unused exports
        for exp in issue.get("exports", []):
            name = exp.get("name", "?")
            line = max(1, int(exp.get("line", 1)))
            fp = normalize.make_content_fingerprint(
                "unused-export:{0}:{1}:{2}".format(file_path, line, name)
            )
            finding = normalize.make_finding(
                check_id="dead-code/unused-export",
                rule_id="knip/unused-export",
                severity="low",
                confidence="medium",
                path=file_path,
                line=line,
                message="Unused export: {0}".format(name),
                fingerprint=fp,
                properties={"tool": "knip"},
            )
            normalize.emit_finding(finding)

        # Unlisted dependencies
        for dep in issue.get("unlisted", []):
            name = dep.get("name", "?") if isinstance(dep, dict) else str(dep)
            fp = normalize.make_content_fingerprint(
                "unlisted-dep:{0}:{1}".format(file_path, name)
            )
            finding = normalize.make_finding(
                check_id="dead-code/unlisted-dependency",
                rule_id="knip/unlisted",
                severity="medium",
                confidence="medium",
                path=file_path,
                line=1,
                message="Unlisted dependency: {0}".format(name),
                fingerprint=fp,
                properties={"tool": "knip", "package": name},
            )
            normalize.emit_finding(finding)

        # Unused dependencies listed in package.json
        for dep in issue.get("dependencies", []):
            name = dep.get("name", "?") if isinstance(dep, dict) else str(dep)
            fp = normalize.make_content_fingerprint(
                "unused-dep:{0}:{1}".format(file_path, name)
            )
            finding = normalize.make_finding(
                check_id="dead-code/unused-dependency",
                rule_id="knip/unused-dependency",
                severity="low",
                confidence="medium",
                path="package.json",
                line=1,
                message="Unused dependency in package.json: {0}".format(name),
                fingerprint=fp,
                properties={"tool": "knip", "package": name},
            )
            normalize.emit_finding(finding)


if __name__ == "__main__":
    main(sys.argv)
