#!/usr/bin/env python3
"""Assertion helper for test-paths-symlink.sh (Epic 1, issue #954).

Kept as a standalone script rather than inline heredocs in the bash
harness for two reasons: it is independently readable/testable, and it
sidesteps the bash 3.2 lexer trap plan.md §2 warns about (an apostrophe
inside a `#` comment inside a quoted heredoc within `$(...)`) entirely,
by never needing a heredoc-in-command-substitution in the first place.

Every subcommand prints exactly one line to stdout and always exits 0 --
the caller (test-paths-symlink.sh) reads stdout to distinguish outcomes,
never the exit code. This matters most for `check-loaded`, where
LOG_MISSING is itself a meaningful, distinct outcome (see
lib/loaded_log.py's LogMissingError vs RuleNotLoadedError split) rather
than a script failure.

Subcommands
-----------
  check-loaded <log_dir> <real_path>
      Scans every loaded-*.jsonl file under <log_dir> (a run may span a
      UTC day boundary and thus write more than one) for a record naming
      <real_path>. Prints one of:
        LOADED       -- at least one log names the rule as loaded
        NOT_LOADED   -- at least one log exists and parses, but none
                        name the rule
        LOG_MISSING  -- no log file exists at all (the hook never fired
                        -- never conflated with NOT_LOADED, per
                        lib/loaded_log.py's design)

  check-no-self-read <out_json> <real_path> <basename>
      Scans the `claude -p --output-format json` event array in
      <out_json> for an assistant `tool_use` block named "Read" whose
      `input.file_path` contains <real_path> or <basename>. Prints:
        OK                        -- no such Read call found
        SELF_READ_DETECTED: <path> -- the first matching Read call
        CHECK_ERROR: <detail>      -- <out_json> could not be parsed
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.environ["LOADED_LOG_LIB"])
import loaded_log  # noqa: E402


def check_loaded(log_dir: str, real_path: str) -> None:
    logs = sorted(glob.glob(os.path.join(log_dir, "loaded-*.jsonl")))
    saw_any_log = False
    for log_path in logs:
        if not os.path.isfile(log_path):
            continue
        saw_any_log = True
        try:
            loaded_log.assert_loaded(log_path, real_path)
            print("LOADED")
            return
        except loaded_log.RuleNotLoadedError:
            continue
        except loaded_log.LogMissingError:
            continue
    print("NOT_LOADED" if saw_any_log else "LOG_MISSING")


def check_no_self_read(out_json_path: str, real_path: str, basename: str) -> None:
    try:
        with open(out_json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CHECK_ERROR: could not parse {out_json_path}: {exc}")
        return

    if not isinstance(data, list):
        data = [data]

    for item in data:
        if not isinstance(item, dict) or item.get("type") != "assistant":
            continue
        message = item.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Read":
                continue
            tool_input = block.get("input") or {}
            file_path = str(tool_input.get("file_path", ""))
            if (real_path and real_path in file_path) or (basename and basename in file_path):
                print(f"SELF_READ_DETECTED: {file_path}")
                return
    print("OK")


def main() -> None:
    if len(sys.argv) < 2:
        print("USAGE_ERROR: no subcommand given")
        return

    subcommand = sys.argv[1]
    if subcommand == "check-loaded" and len(sys.argv) == 4:
        check_loaded(sys.argv[2], sys.argv[3])
    elif subcommand == "check-no-self-read" and len(sys.argv) == 5:
        check_no_self_read(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(f"USAGE_ERROR: bad invocation: {sys.argv[1:]!r}")


if __name__ == "__main__":
    main()
