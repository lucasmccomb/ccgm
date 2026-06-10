#!/usr/bin/env python3
"""
CCGM audit spine -- parse pinact output -> finding.schema.json JSONL.

Usage: parse-pinact.py <pinact_output_file> <repo_root>

# -------------------------------------------------------------------------
# Assumed pinact output shape (documented; not installed locally)
#
# pinact run --check emits a diff-like text to stdout.
# Each unpinned action produces a block like:
#
#   .github/workflows/ci.yml
#     uses: actions/checkout@v4
#   ->
#     uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4
#
# Alternatively, pinact may emit one line per finding in a more structured form:
#
#   .github/workflows/ci.yml:12: actions/checkout@v4 -> actions/checkout@<sha> # v4
#
# We handle BOTH formats:
#   1. "file:line: action@ref" lines (structured single-line format).
#   2. Multi-line diff blocks starting with a bare filename followed by "uses:" lines.
#
# For format 1, a line matches the pattern:
#   ^<filepath>:[0-9]+: <owner>/<repo>@<ref> ->
#
# For format 2, a diff block looks like:
#   ^<filepath>$              (bare filename, no colon-number)
#   ^  uses: <owner>/<repo>@<ref>$   (the unpinned reference)
#   ^->$                              (arrow separator)
#   ^  uses: <owner>/<repo>@<sha>    (the pinned suggestion)
#
# In both cases we extract: filepath, line number (if present, else 1),
# action reference (e.g. "actions/checkout@v4"), and emit one
# cicd/unpinned-action finding per action.
#
# A third fallback: any "uses:" line containing an action ref that does NOT
# look like a 40-char hex SHA is treated as a finding. This handles output
# formats we haven't seen but that still contain "uses:" lines.
# -------------------------------------------------------------------------
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import normalize  # noqa: E402


# Regex: structured single-line format
# e.g. ".github/workflows/ci.yml:12: actions/checkout@v4 ->"
_STRUCTURED_RE = re.compile(
    r"^(?P<path>[^\s:][^\s]*\.ya?ml):(?P<line>\d+):\s+"
    r"(?P<action>[^\s@]+@[^\s]+)"
    r"\s+->"
)

# Regex: "uses:" line inside a diff block
# e.g. "  uses: actions/checkout@v4" or "- uses: actions/checkout@v4"
_USES_RE = re.compile(
    r"^\s*(?:[-+])?\s*uses:\s+(?P<action>[^\s@]+@(?P<ref>[^\s#]+))"
)

# A fully-pinned ref is a 40-char hex SHA (optionally followed by comment)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _is_sha(ref):
    return bool(_SHA_RE.match(ref.split()[0].strip()))


def process_pinact(text, repo_root):
    """Parse pinact output text and emit normalized findings."""
    lines = text.splitlines()
    emitted = set()  # deduplicate by (path, action)

    # Pass 1: structured single-line format
    for raw in lines:
        m = _STRUCTURED_RE.match(raw)
        if m:
            file_path = m.group("path")
            if file_path.startswith(repo_root + "/"):
                file_path = file_path[len(repo_root) + 1:]
            line_no = max(1, int(m.group("line")))
            action = m.group("action")
            key = (file_path, action)
            if key in emitted:
                continue
            emitted.add(key)
            _emit_unpinned(file_path, line_no, action, repo_root)
        # Track the current file from bare filename lines for pass 2
    # Pass 2: diff-block / "uses:" line format
    # Walk lines; when we see a "uses:" line that is unpinned, emit a finding.
    # We track the current file from preceding bare filename lines.
    current_file = None
    current_line = 0

    for raw in lines:
        stripped = raw.strip()

        # Bare filename line (no line number suffix, ends with .yml/.yaml)
        if re.match(r"^[^\s:]+\.ya?ml$", stripped) and not stripped.startswith("-"):
            candidate = stripped
            if candidate.startswith(repo_root + "/"):
                candidate = candidate[len(repo_root) + 1:]
            current_file = candidate
            current_line = 0
            continue

        # "uses:" line
        m = _USES_RE.match(raw)
        if m:
            action = m.group("action")
            ref = m.group("ref").rstrip()
            if not _is_sha(ref):
                file_path = current_file or ".github/workflows/unknown.yml"
                line_no = max(1, current_line)
                key = (file_path, action)
                if key not in emitted:
                    emitted.add(key)
                    _emit_unpinned(file_path, line_no, action, repo_root)
            continue

        # Line-number tracking: look for ":<number>:" patterns embedded in lines
        lno_m = re.search(r":(\d+):", raw)
        if lno_m and current_file:
            current_line = int(lno_m.group(1))


def _emit_unpinned(file_path, line_no, action, _repo_root):
    """Emit one cicd/unpinned-action finding."""
    # action is e.g. "actions/checkout@v4"
    message = "Unpinned action: {0} (use a full commit SHA instead of a mutable ref)".format(action)
    fp = normalize.make_content_fingerprint(
        "{0}:{1}:{2}".format(file_path, line_no, action)
    )
    finding = normalize.make_finding(
        check_id="cicd/unpinned-action",
        rule_id="pinact/unpinned-uses",
        severity="high",
        confidence="high",
        path=file_path,
        line=line_no,
        message=message,
        fingerprint=fp,
        properties={"tool": "pinact", "action_ref": action},
    )
    normalize.emit_finding(finding)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("Usage: parse-pinact.py <pinact_output_file> <repo_root>\n")
        sys.exit(1)

    output_file = argv[1]
    repo_root = argv[2].rstrip("/")

    if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
        # No output from pinact (no unpinned actions found) -- emit nothing
        return

    try:
        with open(output_file, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        process_pinact(text, repo_root)
    except OSError as exc:
        sys.stderr.write("Cannot read pinact output: {0}\n".format(exc))


if __name__ == "__main__":
    main(sys.argv)
