"""Parsing library for the InstructionsLoaded measurement log (Epic 7).

Consumes the JSONL log written by
`modules/relevance-injection/hooks/instructions-loaded-log.py` at
`~/.claude/rule-loading/loaded-{YYYY-MM-DD}.jsonl` (or wherever
`$CCGM_RULE_LOADING_DIR` points a test at).

Two entry points, both pure functions of the filesystem (no hook I/O):

    parse_log(path) -> list[dict]
        Read a single JSONL log file into a list of record dicts.

    assert_loaded(path, rule_path) -> None
        Raise if `rule_path` was NOT recorded as loaded in the log at
        `path`. Raises a DIFFERENT, distinctly named exception depending
        on whether the log itself is missing (LogMissingError) versus
        present but not naming the rule (RuleNotLoadedError). This
        distinction is load-bearing for Epic 1's negative arm: a missing
        log must never be silently read as "the rule was absent", or a
        broken harness would masquerade as a passing negative assertion.

See modules/relevance-injection/hooks/instructions-loaded-log.py for the
observed payload shape this module parses.
"""
from __future__ import annotations

import json
import os


class LogMissingError(Exception):
    """The InstructionsLoaded log file does not exist at all.

    Distinct from RuleNotLoadedError on purpose: a missing log means the
    assertion could not be evaluated (the hook never fired, the wrong
    path was checked, the session never ran) -- it is not evidence that
    the rule was absent from a session that actually ran.
    """


class RuleNotLoadedError(Exception):
    """The log exists and parses, but no record names the given rule path."""


def parse_log(path: "str | os.PathLike") -> "list[dict]":
    """Parse a JSONL InstructionsLoaded log into a list of record dicts.

    - Missing file -> raises FileNotFoundError (standard, distinctly
      named; assert_loaded() below translates this into LogMissingError
      for its own contract).
    - Empty file -> returns [].
    - A line that is not valid JSON, or that parses to something other
      than a JSON object, is skipped -- never raised. One corrupt line
      must not prevent every other record in the log from being read.
    - A line carrying invalid UTF-8 never raises. The decode happens in
      the line iterator, outside any json.loads() guard, so without
      `errors="replace"` a single corrupt byte would abort the whole
      parse and discard every other record in the file -- including the
      valid ones written before it. With replacement, the undecodable
      bytes become U+FFFD and the line is then treated like any other:
      kept if it still parses as a JSON object, dropped if it does not.
      A retained record cannot cause a false positive in assert_loaded()
      because no real rule path contains U+FFFD.
    - A line that parses to a JSON object is appended to the result
      as-is.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    records: "list[dict]" = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _loaded_file_paths(records: "list[dict]") -> "set[str]":
    """Collect every `file_path` named across all records.

    Reads the top-level `file_path` field the hook extracts directly, and
    falls back to the same field inside the preserved `raw` payload -- so
    a record written before a future field-name change (or one that hit
    the extraction's `None` fallback for any reason) is not silently
    invisible to this check.
    """
    paths: "set[str]" = set()
    for record in records:
        file_path = record.get("file_path")
        if isinstance(file_path, str) and file_path:
            paths.add(file_path)

        raw = record.get("raw")
        if isinstance(raw, dict):
            raw_file_path = raw.get("file_path")
            if isinstance(raw_file_path, str) and raw_file_path:
                paths.add(raw_file_path)
    return paths


def _matches(loaded_path: str, rule_path: str) -> bool:
    """True if `loaded_path` (as recorded) corresponds to `rule_path`.

    Exact match covers the common case where the caller passes the same
    absolute path the hook recorded. Suffix match on a normalized
    "/"-separated tail covers a caller passing a shorter, module-relative
    path such as "rules/tailwind.md" against a recorded absolute path
    like "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md".
    """
    if loaded_path == rule_path:
        return True
    normalized_rule = rule_path.lstrip("/")
    return loaded_path.endswith("/" + normalized_rule) or loaded_path == normalized_rule


def assert_loaded(path: "str | os.PathLike", rule_path: str) -> None:
    """Assert that `rule_path` was recorded as a loaded instruction file.

    Raises:
        LogMissingError: the log file at `path` does not exist. This is
            NEVER treated as "the rule was not loaded" -- it means the
            assertion has no evidence to evaluate at all.
        RuleNotLoadedError: the log exists and parses, but no record
            names `rule_path` as a loaded file.

    Returns None (no exception) if at least one record names the rule.
    """
    try:
        records = parse_log(path)
    except FileNotFoundError as exc:
        raise LogMissingError(f"InstructionsLoaded log not found: {path}") from exc

    loaded_paths = _loaded_file_paths(records)
    for loaded_path in loaded_paths:
        if _matches(loaded_path, rule_path):
            return

    raise RuleNotLoadedError(
        f"{rule_path!r} was not recorded as loaded in {path} "
        f"({len(records)} record(s), {len(loaded_paths)} distinct file(s) loaded)"
    )
