#!/usr/bin/env python3
"""
CCGM audit spine — shared normalizer helpers + CLI entry point.

Dual-use:
  1. Library: other Python normalizers import from this module.
  2. CLI: called by bash wrappers for simple skip/gap emission.

CLI modes (argv[1]):
  --emit-skip  <tool>  <"check_id:description" ...>
      Emits a skipped note + one coverage-gap per pair, then exits 0.

No third-party deps -- stdlib only.
"""

import hashlib
import json
import re
import sys


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def compute_fingerprint(file_lines, line_no, gen=1):
    """
    Compute a stable fingerprint for a finding.

    fingerprint = sha256( lower( strip_all_whitespace( primary line +/- 2 lines ) ) )[:16] + ":<gen>"

    file_lines: list of strings (file content, 0-indexed)
    line_no:    1-based line number of the primary finding line
    gen:        fingerprint generation (default 1)
    """
    idx = line_no - 1  # convert to 0-based
    start = max(0, idx - 2)
    end = min(len(file_lines), idx + 3)
    context = "".join(file_lines[start:end])
    normalized = re.sub(r"\s+", "", context).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return "{0}:{1}".format(digest[:16], gen)


_FINGERPRINT_RE = re.compile(r"^[A-Za-z0-9_.:+/=-]{8,128}$")


def validate_tool_fingerprint(tool_fp):
    """
    Return the stripped tool-supplied fingerprint if it matches the finding
    schema fingerprint pattern ^[A-Za-z0-9_.:+/=-]{8,128}$, otherwise None.

    Semgrep emits 'requires login' (contains a space) when not authenticated
    to Semgrep Cloud; that placeholder fails the schema and must be discarded
    so callers fall back to compute_fingerprint().
    """
    stripped = tool_fp.strip() if tool_fp else ""
    if stripped and _FINGERPRINT_RE.match(stripped):
        return stripped
    return None


def fingerprint_from_tool(tool_fp):
    """
    Return a validated tool-supplied fingerprint (stripped), or None if the
    value fails the fingerprint schema pattern ^[A-Za-z0-9_.:+/=-]{8,128}$.

    Per plan ss3.7: where a spine tool emits its own partialFingerprints,
    use the tool's fingerprint -- but only if it is schema-valid.  Invalid
    values (e.g. semgrep's 'requires login' placeholder when not logged into
    Semgrep Cloud) are discarded so callers fall back to compute_fingerprint().
    """
    return validate_tool_fingerprint(tool_fp)


def make_content_fingerprint(content, gen=1):
    """
    Compute a fingerprint directly from a content string (for findings
    without a file context, e.g. dependency findings).
    """
    normalized = re.sub(r"\s+", "", content).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return "{0}:{1}".format(digest[:16], gen)


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

# Patterns for credential-like values.
_SECRET_PATTERN = re.compile(
    r"""(?xi)
    (?:
        # keyword = value  (group 1 = value)
        (?:api[_\-]?key|access[_\-]?token|secret[_\-]?key|auth[_\-]?token|
           bearer|password|passwd|credential|private[_\-]?key|api[_\-]?secret)
        \s*[=:]\s*
        ['""]?([A-Za-z0-9+/._\-]{8,})['""]?
    )
    |
    (?:
        # Bare token prefixes (group 2)
        (ghp_[A-Za-z0-9]{36,}|sk-[A-Za-z0-9\-]{20,}|
         xox[bpoas]-[A-Za-z0-9\-]+|
         AKIA[A-Z0-9]{16}|
         ya29\.[A-Za-z0-9\-_]+|
         AIza[A-Za-z0-9\-_]{35,})
    )
    """,
    re.IGNORECASE,
)


def redact_secret(value):
    """
    Redact a secret value: keep first 4 chars, show total length.
    e.g. "ghp_AbcXyz123..." -> "ghp_[redacted:len=40]"
    """
    if len(value) <= 4:
        return "[redacted:len={0}]".format(len(value))
    return "{0}[redacted:len={1}]".format(value[:4], len(value))


def redact_message(message):
    """
    Scan a finding message for credential-like values and redact them.
    Only the captured value group (not the keyword prefix) is redacted.
    """
    def _replace(m):
        full = m.group(0)
        secret_val = m.group(1) or m.group(2)
        if secret_val and len(secret_val) >= 8:
            return full.replace(secret_val, redact_secret(secret_val), 1)
        return full

    return _SECRET_PATTERN.sub(_replace, message)


# ---------------------------------------------------------------------------
# Finding construction
# ---------------------------------------------------------------------------

def make_finding(
    check_id,
    rule_id,
    severity,
    confidence,
    path,
    line,
    message,
    fingerprint,
    end_line=None,
    fix_confidence=None,
    properties=None,
    detection="tool",
):
    """
    Build a finding dict conforming to finding.schema.json.
    Automatically redacts the message field.

    detection: "tool" (default) for deterministic, lockfile/manifest-grade
    findings that must NOT be dismissible (dep-audit, govulncheck, ...).
    Heuristic, FP-prone scanners (gitleaks, semgrep, bandit) pass "hybrid" so
    worker triage can dismiss false positives on test fixtures and the like
    (field report #4); a hybrid finding is dropped only if EVERY worker that
    named it voted "dismissed".  source stays "tool" -- the spine produced it.
    """
    if detection not in ("tool", "hybrid"):
        detection = "tool"
    finding = {
        "check_id": check_id,
        "rule_id": rule_id,
        "severity": severity,
        "confidence": confidence,
        "location": {
            "path": path,
            "line": line,
        },
        "message": redact_message(message),
        "fingerprint": fingerprint,
        "detection": detection,
        "source": "tool",
    }
    if end_line is not None and end_line >= line:
        finding["location"]["end_line"] = end_line
    if fix_confidence is not None:
        finding["fix_confidence"] = fix_confidence
    if properties:
        finding["properties"] = properties
    return finding


# ---------------------------------------------------------------------------
# Coverage gap / skip note
# ---------------------------------------------------------------------------

def make_skipped_note(tool, reason="not installed"):
    """Build a skipped note dict."""
    return {
        "type": "skipped",
        "tool": tool,
        "reason": reason,
    }


def make_coverage_gap(tool, check_id, description):
    """
    Build a coverage-gap entry for a tool-backed check that could not run.
    Per plan ss3.6: coverage_gaps[] is first-class output.
    """
    return {
        "type": "coverage_gap",
        "tool": tool,
        "check_id": check_id,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def emit_finding(finding):
    """Print a finding as a JSONL line to stdout."""
    sys.stdout.write(json.dumps(finding, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_note(note):
    """Print a note/coverage-gap as a JSONL line to stdout."""
    sys.stdout.write(json.dumps(note, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_skip_and_exit(tool, gaps):
    """
    Emit a skipped note + one coverage-gap entry per (check_id, description)
    tuple in gaps.  Exits 0 -- absent tools are not errors.

    gaps: list of (check_id, description) tuples
    """
    emit_note(make_skipped_note(tool))
    for check_id, description in gaps:
        emit_note(make_coverage_gap(tool, check_id, description))
    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI entry point (used by bash wrappers)
# ---------------------------------------------------------------------------

def _cli(argv):
    """
    CLI: normalize.py --emit-skip <tool> <"check_id:description" ...>
    """
    if len(argv) < 2:
        sys.stderr.write(
            "Usage: normalize.py --emit-skip <tool> <check_id:description ...>\n"
        )
        sys.exit(1)

    mode = argv[1]

    if mode == "--emit-skip":
        if len(argv) < 3:
            sys.stderr.write("--emit-skip requires <tool> argument\n")
            sys.exit(1)
        tool = argv[2]
        gaps = []
        for item in argv[3:]:
            if ":" in item:
                check_id, _, description = item.partition(":")
                gaps.append((check_id.strip(), description.strip()))
        emit_skip_and_exit(tool, gaps)
    else:
        sys.stderr.write("Unknown mode: {0}\n".format(mode))
        sys.exit(1)


if __name__ == "__main__":
    _cli(sys.argv)
