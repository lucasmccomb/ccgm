#!/usr/bin/env python3
"""
CCGM /audit suppression applier (Epic 3.3).

Reads a JSONL findings file (merge-findings output) and applies suppression
rules from a .auditignore.yaml file and/or inline source-file comments.
Suppressed findings are KEPT in the output with a ``suppression`` field set;
they are never omitted.

Usage
-----
  suppress.py --findings <findings.jsonl>
              [--auditignore <path>]
              [--repo <root>]
              [--output <file>]
              [--today YYYY-MM-DD]

Arguments
---------
  --findings  <path>        Required. JSONL produced by merge-findings.py (or
                            baseline.py).
  --auditignore <path>      Path to .auditignore.yaml.  Default: <repo>/.auditignore.yaml
                            when that file exists, otherwise no file-level suppressions
                            are applied.
  --repo <path>             Absolute path to the repository root.  Used to (a) find the
                            default .auditignore.yaml and (b) resolve location.path when
                            scanning source files for inline comments.
                            Default: current working directory.
  --output <file>           Write output JSONL to this file.  Default: stdout.
  --today YYYY-MM-DD        Override "today" for expiry comparisons.  Useful for
                            deterministic testing.  Default: date.today() from the
                            system clock.

.auditignore.yaml format — supported subset
--------------------------------------------
The parser handles a STRICT, fixed YAML subset. Shapes outside this subset
cause a hard error (exit 1) — they are NEVER silently mis-parsed.

  Supported top-level structure:
    A sequence (YAML list) of mapping blocks.

  Each mapping block may contain these scalar or inline-list keys:
    id: <check-id or fnmatch glob>          # also accepted: check_id
    paths: [<glob>, ...]                     # inline list of repo-relative globs
    reason: <string>                         # REQUIRED
    expires: YYYY-MM-DD                      # optional

  Supported value types:
    - Scalars (unquoted, single-quoted, or double-quoted strings)
    - Inline lists: [item1, item2, ...]

  NOT supported (will raise a parse error):
    - Multi-line block scalars (|, >)
    - Multi-line block sequences (paths written as indented list items
      under the key rather than as an inline list)
    - Nested mappings
    - Anchors and aliases (&anchor, *alias)
    - Complex YAML keys
    - Documents starting with ---

  If an entry is missing ``reason``, a warning is printed to stderr and
  that entry is SKIPPED (the finding is not suppressed by that entry).

Inline comment format
---------------------
  # audit-ignore: <check-id> [optional reason text]
  // audit-ignore: <check-id> [optional reason text]

  The suppression applies to the finding on the SAME LINE as the comment
  OR the immediately FOLLOWING LINE.

  Block-scoping rule:
    Line N carries "# audit-ignore: foo/bar".
    A finding at location.line == N  (same line) is suppressed for foo/bar.
    A finding at location.line == N+1 (next line) is also suppressed for foo/bar.
    Findings on any other line are not suppressed by that comment.

  Only the named check-id is suppressed at that location (the comment is
  check-id-specific, not blanket-ignore-everything).

Expiry
------
  If ``expires`` is present on a .auditignore.yaml entry and its date is
  STRICTLY BEFORE ``--today`` (or today's date), the suppression is NOT
  applied and a warning is emitted to stderr naming the entry.

  Pass ``--today YYYY-MM-DD`` to make expiry checks deterministic in tests.
  Internally, the date is obtained via ``datetime.date.today()`` when --today
  is absent; pass --today to override.

Output
------
  Full JSONL: all input records (finding and non-finding) passed through.
  Finding records that matched a suppression rule gain a ``suppression``
  field:
    {"justification": "<reason or inline reason or 'inline'>",
     "expires": "<YYYY-MM-DD>"}     <- only when an expires date was set

  Records with a ``type`` field (provenance, coverage_gap, etc.) are passed
  through unchanged.

Exit codes
----------
  0  Success.
  1  Malformed input or parse error.
"""

import argparse
import datetime
import fnmatch
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal YAML subset parser
# ---------------------------------------------------------------------------

class _YAMLParseError(Exception):
    pass


def _parse_scalar(raw: str) -> str:
    """
    Parse a YAML scalar value: unquoted, single-quoted, or double-quoted.
    Raises _YAMLParseError on unsupported shapes (block scalars, etc.).
    """
    raw = raw.strip()
    if not raw:
        return ""
    # Block-scalar indicators
    if raw[0] in ("|", ">"):
        raise _YAMLParseError(
            f"block scalars (| >) are not supported: {raw!r}"
        )
    # Double-quoted string
    if raw.startswith('"'):
        if not raw.endswith('"') or len(raw) < 2:
            raise _YAMLParseError(f"unterminated double-quoted string: {raw!r}")
        return raw[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
    # Single-quoted string
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise _YAMLParseError(f"unterminated single-quoted string: {raw!r}")
        return raw[1:-1].replace("''", "'")
    # Anchors / aliases are unsupported
    if raw[0] in ("&", "*"):
        raise _YAMLParseError(f"anchors and aliases are not supported: {raw!r}")
    # Unquoted scalar — return as-is (stripped)
    return raw


def _parse_inline_list(raw: str) -> list:
    """
    Parse an inline YAML list: [item1, item2, ...].
    Items may be quoted or unquoted scalars.
    Raises _YAMLParseError on parse failure or nested structures.
    """
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        raise _YAMLParseError(f"expected inline list starting with '[': {raw!r}")
    inner = raw[1:-1].strip()
    if not inner:
        return []
    # Detect nested brackets
    if "[" in inner:
        raise _YAMLParseError(f"nested lists are not supported: {raw!r}")
    # Split on commas, parse each item as a scalar
    parts = [p.strip() for p in inner.split(",")]
    return [_parse_scalar(p) for p in parts if p]


def _parse_auditignore_yaml(path: str) -> list:
    """
    Parse .auditignore.yaml using the supported subset parser.

    Returns a list of entry dicts:
      {
        "id":      str,            # check-id or glob (normalized from id or check_id)
        "paths":   list[str],      # repo-relative globs
        "reason":  str | None,     # None means missing (caller should warn+skip)
        "expires": str | None,     # YYYY-MM-DD or None
      }

    Raises _YAMLParseError on unsupported YAML shapes.
    Exits 1 with a clear message on file-read errors.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"suppress: ERROR: cannot read .auditignore.yaml at {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    lines = text.splitlines()

    # Strip full-line comments and blank lines; track original line numbers for errors.
    effective: list = []  # list of (lineno, text)
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        # Ignore blank lines and full-line comments
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        effective.append((i, stripped))

    if not effective:
        return []

    # The document must be a top-level list (sequence of dashes).
    # Reject YAML documents that start with --- (document separator).
    if effective[0][1].strip().startswith("---"):
        raise _YAMLParseError(
            "YAML document separators (---) are not supported; "
            "omit the --- line before the list"
        )

    # Each entry begins with "- " at column 0 (or "- " at any indent within
    # the top-level list).  We collect blocks of lines per entry.
    entry_blocks: list = []  # list of list-of-(lineno, text)
    current_block: list = []

    for lineno, text in effective:
        # A new list item begins at the line with leading "- " (stripped).
        stripped = text.lstrip()
        indent_len = len(text) - len(stripped)
        if stripped.startswith("- ") and indent_len == 0:
            if current_block:
                entry_blocks.append(current_block)
            current_block = [(lineno, text)]
        elif stripped.startswith("- ") and indent_len > 0:
            # Indented list items inside an entry (e.g. block-style paths list) —
            # we do NOT support this; block-style sequences are unsupported.
            raise _YAMLParseError(
                f"line {lineno}: indented list items under a key are not supported; "
                "use inline list syntax: paths: [glob1, glob2]"
            )
        else:
            if not current_block:
                raise _YAMLParseError(
                    f"line {lineno}: expected a list entry starting with '- '"
                )
            current_block.append((lineno, text))

    if current_block:
        entry_blocks.append(current_block)

    entries = []
    for block in entry_blocks:
        entry = _parse_entry_block(block)
        entries.append(entry)
    return entries


_KV_RE = re.compile(r"^-?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)")


def _parse_entry_block(block: list) -> dict:
    """
    Parse a single entry block (list of (lineno, text) tuples) into a dict.
    The first line starts with "- " (the list-item marker).
    """
    entry: dict = {"id": None, "paths": [], "reason": None, "expires": None}
    seen_keys: set = set()

    for lineno, text in block:
        # Strip the leading "- " from the first line
        stripped = text.lstrip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        else:
            stripped = stripped.lstrip()

        if not stripped:
            continue

        m = _KV_RE.match(stripped)
        if not m:
            raise _YAMLParseError(
                f"line {lineno}: expected 'key: value' pair, got: {text!r}"
            )

        key = m.group(1).strip()
        value_raw = m.group(2).strip()

        if key in seen_keys:
            raise _YAMLParseError(
                f"line {lineno}: duplicate key {key!r} in entry"
            )
        seen_keys.add(key)

        if key in ("id", "check_id"):
            entry["id"] = _parse_scalar(value_raw)
        elif key == "paths":
            if value_raw.startswith("["):
                entry["paths"] = _parse_inline_list(value_raw)
            elif value_raw:
                # Single value (not a list) treated as a single-item list
                entry["paths"] = [_parse_scalar(value_raw)]
            else:
                entry["paths"] = []
        elif key == "reason":
            entry["reason"] = _parse_scalar(value_raw)
        elif key == "expires":
            entry["expires"] = _parse_scalar(value_raw)
        else:
            raise _YAMLParseError(
                f"line {lineno}: unknown key {key!r}; "
                "supported keys: id (or check_id), paths, reason, expires"
            )

    return entry


# ---------------------------------------------------------------------------
# Inline comment scanner
# ---------------------------------------------------------------------------

# Pattern: "# audit-ignore: check/id optional reason" or "// audit-ignore: ..."
_INLINE_IGNORE_RE = re.compile(
    r"""
    (?:\#|//)          # comment marker: # or //
    \s*
    audit-ignore:      # keyword
    \s+
    ([^\s]+)           # check-id (no whitespace)
    (?:\s+(.+))?       # optional reason (rest of line)
    """,
    re.VERBOSE,
)


def _scan_inline_ignores(source_path: str) -> dict:
    """
    Scan a source file for audit-ignore inline comments.

    Returns a dict mapping (check_id, line_number) -> reason_str.
    The suppression covers the comment line itself AND the immediately
    following line:
      key (check_id, N)   -> comment on line N suppresses a finding on line N
      key (check_id, N+1) -> comment on line N also suppresses line N+1

    If the file cannot be read (missing, binary, permission), returns {}.
    """
    try:
        with open(source_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return {}

    result: dict = {}
    for i, line in enumerate(lines, 1):
        m = _INLINE_IGNORE_RE.search(line)
        if not m:
            continue
        check_id = m.group(1).strip()
        reason = m.group(2).strip() if m.group(2) else "inline"
        # Cover the comment line itself and the following line.
        result[(check_id, i)] = reason
        result[(check_id, i + 1)] = reason
    return result


# ---------------------------------------------------------------------------
# Expiry check
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime.date:
    """Parse YYYY-MM-DD or raise ValueError."""
    return datetime.date.fromisoformat(date_str)


def _is_expired(expires_str: str, today: datetime.date) -> bool:
    """Return True if the expires date is strictly before today."""
    try:
        exp = _parse_date(expires_str)
    except ValueError:
        return False  # malformed — don't suppress but don't error
    return exp < today


# ---------------------------------------------------------------------------
# Main suppression logic
# ---------------------------------------------------------------------------

def _apply_suppressions(
    findings: list,
    auditignore_entries: list,
    inline_cache: dict,
    repo_root: Path,
    today: datetime.date,
) -> list:
    """
    Apply suppression rules to findings in-place (on copies).

    auditignore_entries: list of parsed entry dicts (already validated — entries
        missing 'reason' have been filtered out by the caller).
    inline_cache: dict of source_path -> {(check_id, line): reason}
        (lazily populated on first access — see _get_inline_for_file).

    Returns the updated findings list (same order, suppression field added
    where applicable).
    """
    result = []
    for f in findings:
        f_copy = dict(f)  # shallow copy — we'll modify suppression field only
        check_id = f_copy.get("check_id", "")
        loc = f_copy.get("location", {})
        path = loc.get("path", "") if isinstance(loc, dict) else ""
        line = loc.get("line", 0) if isinstance(loc, dict) else 0

        # ----------------------------------------------------------------
        # 1. Check .auditignore.yaml rules
        # ----------------------------------------------------------------
        for entry in auditignore_entries:
            entry_id = entry.get("id") or ""
            # check-id must match (exact or fnmatch glob)
            if not (entry_id == check_id or fnmatch.fnmatch(check_id, entry_id)):
                continue
            # path must match at least one glob in paths (if paths is specified)
            entry_paths = entry.get("paths", [])
            if entry_paths:
                if not any(fnmatch.fnmatch(path, p) for p in entry_paths):
                    continue
            # Expiry check
            expires = entry.get("expires")
            if expires and _is_expired(expires, today):
                continue
            # Apply suppression
            sup: dict = {"justification": entry.get("reason", "")}
            if expires:
                sup["expires"] = expires
            f_copy["suppression"] = sup
            break  # first matching rule wins

        # ----------------------------------------------------------------
        # 2. Check inline comments (only if not already suppressed)
        # ----------------------------------------------------------------
        if "suppression" not in f_copy and path and line:
            inline_map = _get_inline_for_file(inline_cache, path, repo_root)
            inline_reason = inline_map.get((check_id, line))
            if inline_reason is not None:
                f_copy["suppression"] = {"justification": inline_reason}

        result.append(f_copy)
    return result


def _get_inline_for_file(cache: dict, rel_path: str, repo_root: Path) -> dict:
    """
    Return the inline-ignore map for a source file, caching the result.
    """
    if rel_path not in cache:
        abs_path = str(repo_root / rel_path) if rel_path else ""
        cache[rel_path] = _scan_inline_ignores(abs_path) if abs_path else {}
    return cache[rel_path]


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------

def _read_jsonl(path: str):
    """
    Read a JSONL file.  Returns list of (raw_line, parsed_obj) tuples.
    Exits 1 with an actionable message on parse errors.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(f"suppress: ERROR: cannot read findings file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)

    records = []
    for lineno, raw in enumerate(raw_lines, 1):
        raw = raw.rstrip("\n")
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            print(
                f"suppress: ERROR: findings file line {lineno} is not valid JSON: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(obj, dict):
            print(
                f"suppress: ERROR: findings file line {lineno} is not a JSON object",
                file=sys.stderr,
            )
            sys.exit(1)
        records.append(obj)
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply .auditignore.yaml + inline comment suppressions to findings JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--findings",
        required=True,
        metavar="PATH",
        help="Findings JSONL (merge-findings or baseline output).",
    )
    parser.add_argument(
        "--auditignore",
        default=None,
        metavar="PATH",
        help=(
            "Path to .auditignore.yaml. "
            "Default: <repo>/.auditignore.yaml when present, otherwise skipped."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        metavar="ABS_PATH",
        help=(
            "Absolute path to the repository root. Used to resolve source file paths "
            "for inline-comment scanning and to locate the default .auditignore.yaml. "
            "Default: current working directory."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write output JSONL to this file. Default: stdout.",
    )
    parser.add_argument(
        "--today",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Override today's date for expiry comparisons (YYYY-MM-DD). "
            "Defaults to datetime.date.today() from the system clock. "
            "Pass this flag to make expiry checks deterministic in tests."
        ),
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve repo root
    # ------------------------------------------------------------------
    repo_root = Path(args.repo).resolve() if args.repo else Path.cwd()

    # ------------------------------------------------------------------
    # Resolve today's date (injectable for deterministic testing)
    # ------------------------------------------------------------------
    if args.today:
        try:
            today = _parse_date(args.today)
        except ValueError:
            print(
                f"suppress: ERROR: --today value {args.today!r} is not a valid YYYY-MM-DD date",
                file=sys.stderr,
            )
            return 1
    else:
        today = datetime.date.today()

    # ------------------------------------------------------------------
    # Load .auditignore.yaml
    # ------------------------------------------------------------------
    auditignore_path = args.auditignore
    if auditignore_path is None:
        default = repo_root / ".auditignore.yaml"
        if default.is_file():
            auditignore_path = str(default)

    auditignore_entries: list = []
    if auditignore_path:
        try:
            raw_entries = _parse_auditignore_yaml(auditignore_path)
        except _YAMLParseError as exc:
            print(
                f"suppress: ERROR: cannot parse .auditignore.yaml at {auditignore_path}: {exc}",
                file=sys.stderr,
            )
            return 1

        for i, entry in enumerate(raw_entries):
            if not entry.get("reason"):
                entry_id = entry.get("id") or f"(entry {i})"
                print(
                    f"suppress: WARNING: .auditignore.yaml entry {i} (id={entry_id!r}) "
                    "is missing required 'reason' field — entry skipped",
                    file=sys.stderr,
                )
                continue
            # Warn on expired entries
            expires = entry.get("expires")
            if expires and _is_expired(expires, today):
                entry_id = entry.get("id") or f"(entry {i})"
                print(
                    f"suppress: WARNING: .auditignore.yaml entry (id={entry_id!r}) "
                    f"has expired (expires={expires!r}, today={today.isoformat()!r}); "
                    "suppression NOT applied",
                    file=sys.stderr,
                )
                continue
            auditignore_entries.append(entry)

    # ------------------------------------------------------------------
    # Read input JSONL
    # ------------------------------------------------------------------
    records = _read_jsonl(args.findings)

    # ------------------------------------------------------------------
    # Separate findings (no type field) from metadata records (have type field)
    # ------------------------------------------------------------------
    findings = []
    metadata = []  # (index, record) tuples preserving original order
    for i, rec in enumerate(records):
        if "type" in rec:
            metadata.append((i, rec))
        else:
            findings.append((i, rec))

    # ------------------------------------------------------------------
    # Apply suppressions to findings
    # ------------------------------------------------------------------
    inline_cache: dict = {}  # rel_path -> {(check_id, line): reason}
    finding_objs = [r for _, r in findings]
    suppressed_objs = _apply_suppressions(
        finding_objs, auditignore_entries, inline_cache, repo_root, today
    )

    # Re-pair with original indices
    suppressed_findings = list(zip([i for i, _ in findings], suppressed_objs))

    # ------------------------------------------------------------------
    # Rebuild output in original record order
    # ------------------------------------------------------------------
    # Merge metadata and findings back by original index
    all_out: list = [None] * len(records)
    for i, rec in metadata:
        all_out[i] = rec
    for i, rec in suppressed_findings:
        all_out[i] = rec

    # ------------------------------------------------------------------
    # Serialize
    # ------------------------------------------------------------------
    output_lines = []
    for rec in all_out:
        if rec is not None:
            output_lines.append(json.dumps(rec, separators=(",", ":")))

    out_text = "\n".join(output_lines)
    if output_lines:
        out_text += "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_text(out_text, encoding="utf-8")
        except OSError as exc:
            print(f"suppress: ERROR: cannot write output: {exc}", file=sys.stderr)
            return 1
        n_suppressed = sum(1 for _, r in suppressed_findings if "suppression" in r)
        print(
            f"suppress: applied suppressions to {n_suppressed} of "
            f"{len(suppressed_findings)} finding(s); wrote to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
