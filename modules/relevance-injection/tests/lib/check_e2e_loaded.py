#!/usr/bin/env python3
"""Checker for test-rules-scope.sh's Part 2 (Gate 2 E2E via InstructionsLoaded).

Usage: check_e2e_loaded.py <lib_dir> <log_path> <retained_target> <excluded_path...>

Prints "OK" and exits 0 if every excluded path is absent from the log and
the retained target is present. Otherwise prints one problem per line and
exits 1. Kept as a standalone script (not an inline `python3 -c` one-liner)
so paths never have to be interpolated into a shell-quoted string literal.
"""
import sys


def main(argv):
    if len(argv) < 4:
        print("usage: check_e2e_loaded.py <lib_dir> <log_path> <retained_target> <excluded_path...>")
        return 2

    lib_dir, log_path, retained_target = argv[1], argv[2], argv[3]
    excluded_paths = [p for p in argv[4:] if p.strip()]

    sys.path.insert(0, lib_dir)
    import loaded_log  # noqa: E402

    problems = []

    for path in excluded_paths:
        try:
            loaded_log.assert_loaded(log_path, path)
        except loaded_log.RuleNotLoadedError:
            continue
        except loaded_log.LogMissingError as exc:
            problems.append("LOG_MISSING:" + str(exc))
            break
        else:
            problems.append("STILL_LOADED:" + path)

    try:
        loaded_log.assert_loaded(log_path, retained_target)
    except loaded_log.RuleNotLoadedError:
        problems.append("RETAINED_MISSING:" + retained_target)
    except loaded_log.LogMissingError as exc:
        problems.append("LOG_MISSING:" + str(exc))

    if problems:
        for p in problems:
            print(p)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
