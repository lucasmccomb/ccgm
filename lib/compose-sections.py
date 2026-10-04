#!/usr/bin/env python3
"""Expand shared prompt sections into the agent and command files that use them.

A section is written once in prompts/sections/<name>.md. A file that uses it
holds a marked block:

    <!-- ccgm:section <name> -->
    ...section text, inlined...
    <!-- /ccgm:section <name> -->

Default mode rewrites every block from its section file. --check changes
nothing and exits 1 when any block differs from its section. Installed files
stay plain markdown; nothing is resolved at runtime.

Scope: modules/*/agents/**/*.md and modules/*/commands/**/*.md. Rule files are
out of scope.

Exit codes: 0 clean (or rewritten), 1 drift found by --check, 2 usage or marker
error (unknown section, unbalanced or nested markers).
"""

import argparse
import re
import sys
from pathlib import Path

START = re.compile(r"^<!-- ccgm:section ([A-Za-z0-9_-]+) -->$")
END = re.compile(r"^<!-- /ccgm:section ([A-Za-z0-9_-]+) -->$")
SCAN_DIRS = ("agents", "commands")


class MarkerError(Exception):
    pass


def load_section(root: Path, name: str) -> str:
    path = root / "prompts" / "sections" / f"{name}.md"
    if not path.is_file():
        raise MarkerError(f"unknown section '{name}' (no {path.relative_to(root)})")
    return path.read_text(encoding="utf-8").rstrip("\n")


def compose(text: str, root: Path, label: str):
    """Return (new_text, drifted_block_names). Raises MarkerError."""
    lines = text.split("\n")
    out = []
    drifted = []
    open_name = None
    open_line = 0
    body = []
    for lineno, line in enumerate(lines, 1):
        m_start = START.match(line)
        m_end = END.match(line)
        if m_start:
            if open_name is not None:
                raise MarkerError(
                    f"{label}:{lineno}: block '{m_start.group(1)}' starts inside "
                    f"block '{open_name}' (opened line {open_line})"
                )
            open_name, open_line, body = m_start.group(1), lineno, []
            out.append(line)
        elif m_end:
            if open_name is None:
                raise MarkerError(f"{label}:{lineno}: end marker '{m_end.group(1)}' with no start")
            if m_end.group(1) != open_name:
                raise MarkerError(
                    f"{label}:{lineno}: end marker '{m_end.group(1)}' closes "
                    f"block '{open_name}' (opened line {open_line})"
                )
            try:
                section = load_section(root, open_name)
            except MarkerError as err:
                raise MarkerError(f"{label}:{open_line}: {err}")
            if "\n".join(body) != section:
                drifted.append(open_name)
            out.extend(section.split("\n") if section else [])
            out.append(line)
            open_name = None
        elif open_name is not None:
            body.append(line)
        else:
            out.append(line)
    if open_name is not None:
        raise MarkerError(f"{label}:{open_line}: block '{open_name}' is never closed")
    return "\n".join(out), drifted


def target_files(root: Path):
    for d in SCAN_DIRS:
        yield from sorted(root.glob(f"modules/*/{d}/**/*.md"))


def main(argv=None) -> int:
    default_root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any block drifted; write nothing")
    ap.add_argument("--root", type=Path, default=default_root, help="repo root (default: this repo)")
    args = ap.parse_args(argv)
    root = args.root.resolve()

    results = []  # (path, new_text, drifted)
    try:
        for path in target_files(root):
            text = path.read_text(encoding="utf-8")
            if "ccgm:section" not in text:
                continue
            label = str(path.relative_to(root))
            new_text, drifted = compose(text, root, label)
            results.append((path, label, new_text, drifted))
    except MarkerError as err:
        print(f"compose-sections: {err}", file=sys.stderr)
        return 2

    drift_found = False
    for path, label, new_text, drifted in results:
        if not drifted:
            continue
        drift_found = True
        if args.check:
            for name in drifted:
                print(f"DRIFT: {label}: block '{name}' differs from prompts/sections/{name}.md", file=sys.stderr)
        else:
            path.write_text(new_text, encoding="utf-8")
            print(f"updated {label} ({', '.join(drifted)})")

    if args.check and drift_found:
        print("compose-sections: run `python3 lib/compose-sections.py` and commit the result", file=sys.stderr)
        return 1
    if args.check:
        print(f"compose-sections: {len(results)} file(s) in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
