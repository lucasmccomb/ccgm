#!/usr/bin/env python3
"""module-index.py - index of CCGM rule files for the autoheal drafting step.

The drafting model must name a real file. This script finds the CCGM source
repo and lists every `modules/*/rules/*.md` path with its H1 and H2 headings
(about 3k tokens), so the prompt can show the model what exists instead of
letting it invent paths (#1099 B4).

Finding the source repo (first match wins, no guessing beyond this):
  1. Config key `ccgm_repo_path` in the autoheal config.json
     ($CCGM_AUTOHEAL_CONFIG, else $CCGM_AUTOHEAL_DIR/config.json, else
     ~/.claude/autoheal/config.json). It overrides everything. If it is set
     but does not point at a CCGM repo, resolution fails: an explicit
     setting is never silently replaced.
  2. The `~/.claude/rules/*.md` symlinks. CCGM installs each rule file as a
     symlink into the repo, so resolving one and walking up to the directory
     that holds `start.sh` and `modules/` gives the repo that supplied the
     installed rules.
  3. Neither: a copy install has no repo to read. Resolution fails with a
     reason and drafting is skipped. Paths are never invented.

Usage:
  module-index.py [--config PATH] [--home DIR] [--repo-root DIR]

Prints one JSON object: {"repo_root", "how", "files": [...], "text"}.
Exit 3 and {"error": "..."} when no repo resolves.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

# Characters of index text. About 3k tokens at ~4 chars per token.
INDEX_BUDGET_CHARS = 12000
MAX_H2_START = 10

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


def is_ccgm_repo(path: str) -> bool:
    return (os.path.isfile(os.path.join(path, "start.sh"))
            and os.path.isdir(os.path.join(path, "modules")))


def find_repo_root(start: str) -> str | None:
    """Walk up from `start` to the first directory that is a CCGM repo."""
    here = os.path.abspath(start)
    while True:
        if is_ccgm_repo(here):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def config_path() -> str:
    explicit = os.environ.get("CCGM_AUTOHEAL_CONFIG")
    if explicit:
        return explicit
    base = os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")
    return os.path.join(base, "config.json")


def resolve_source_repo(cfg_path: str | None = None, home: str | None = None):
    """Return (repo_root, how). repo_root is None on failure; `how` is then the reason."""
    cfg_path = cfg_path or config_path()
    home = home or os.path.expanduser("~")
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    override = cfg.get("ccgm_repo_path") if isinstance(cfg, dict) else None
    if isinstance(override, str) and override.strip():
        root = os.path.abspath(os.path.expanduser(override.strip()))
        if is_ccgm_repo(root):
            return root, "config:ccgm_repo_path"
        return None, f"ccgm_repo_path {root} is not a CCGM repo (needs start.sh and modules/)"

    for link in sorted(glob.glob(os.path.join(home, ".claude", "rules", "*.md"))):
        if not os.path.islink(link):
            continue
        root = find_repo_root(os.path.dirname(os.path.realpath(link)))
        if root:
            return root, "rules-symlink"
    return None, ("no ~/.claude/rules/*.md symlink resolves to a CCGM repo "
                  "(copy install?); set ccgm_repo_path in the autoheal config")


def parse_headings(text: str):
    """(h1, [h2, ...]) outside fenced code blocks. h1 is None when absent."""
    h1 = None
    h2s = []
    fence = None
    for line in text.split("\n"):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence:
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        level, title = len(h.group(1)), h.group(2).strip()
        if level == 1 and h1 is None:
            h1 = title
        elif level == 2:
            h2s.append(title)
    return h1, h2s


def rule_files(root: str) -> list[str]:
    """Repo-relative POSIX paths of every modules/*/rules/*.md, sorted."""
    paths = glob.glob(os.path.join(root, "modules", "*", "rules", "*.md"))
    return sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in paths)


def _render(entries: list[dict], max_h2: int) -> str:
    lines = []
    for e in entries:
        head = f"{e['path']}  # {e['h1']}" if e["h1"] else e["path"]
        h2 = e["h2"][:max_h2]
        more = len(e["h2"]) - len(h2)
        if h2:
            head += "  ## " + " | ".join(h2) + (f" | (+{more} more)" if more else "")
        lines.append(head)
    return "\n".join(lines)


def build_index(root: str, budget_chars: int = INDEX_BUDGET_CHARS) -> dict:
    """Index of the repo's rule files; H2 lists shrink until the text fits."""
    entries = []
    for rel in rule_files(root):
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
                h1, h2 = parse_headings(fh.read())
        except OSError:
            continue
        entries.append({"path": rel, "h1": h1, "h2": h2})
    max_h2 = MAX_H2_START
    text = _render(entries, max_h2)
    while len(text) > budget_chars and max_h2 > 0:
        max_h2 -= 1
        text = _render(entries, max_h2)
    return {"files": entries, "text": text}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", help="autoheal config.json (default: resolved from env)")
    ap.add_argument("--home", help="home dir holding .claude/rules (default: ~)")
    ap.add_argument("--repo-root", help="skip resolution and index this repo")
    args = ap.parse_args(argv)
    if args.repo_root:
        root, how = os.path.abspath(args.repo_root), "argument"
        if not is_ccgm_repo(root):
            root, how = None, f"{args.repo_root} is not a CCGM repo"
    else:
        root, how = resolve_source_repo(args.config, args.home)
    if root is None:
        print(json.dumps({"error": how}))
        return 3
    index = build_index(root)
    print(json.dumps({"repo_root": root, "how": how, **index}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
