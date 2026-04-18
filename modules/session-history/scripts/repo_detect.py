#!/usr/bin/env python3
"""Detect the canonical repo name from a cwd, and list Claude Code project
directories for all clones of that repo.

Used by /recall to unify session transcripts across clones.
"""
import os
import re
import subprocess
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Regex matches a clone suffix on a path basename:
#   flat clone:     "ccgm-0", "ccgm-1", "habitpro-ai-0"
#   workspace:      "ccgm-w0", "habitpro-ai-w1"
#   workspace+clone: "ccgm-w0-c2", "habitpro-ai-w1-c3"
CLONE_SUFFIX = re.compile(r"-(?:w\d+(?:-c\d+)?|\d+)$")


def detect_repo(cwd: str | None = None) -> str | None:
    """Return the canonical repo name for the given cwd (defaults to os.getcwd()).

    Strategy:
    1. Prefer `git remote get-url origin` and parse the repo name from it.
    2. Fall back to the cwd basename with any clone-suffix regex stripped.
    3. Return None if cwd is not inside any git repo and the basename heuristic
       does not strip anything (i.e., we do not know this is a repo).
    """
    cwd = cwd or os.getcwd()
    cwd_path = Path(cwd).resolve()

    # Try git remote first
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            url = out.stdout.strip()
            # Handle git@github.com:user/repo.git and https://github.com/user/repo.git
            name = url.rstrip("/").rsplit("/", 1)[-1].rstrip(".git")
            if name:
                return name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: strip clone-suffix from cwd basename
    basename = cwd_path.name
    stripped = CLONE_SUFFIX.sub("", basename)
    if stripped != basename:
        return stripped

    # No confident detection
    return None


def list_project_dirs(repo: str) -> list[Path]:
    """Return all Claude Code project directories that represent a clone of
    the named repo.

    Claude Code encodes cwd paths by replacing '/' with '-' in the project-dir
    name. Example: /home/alice/code/myrepo/myrepo-1 becomes
    -home-alice-code-myrepo-myrepo-1. Decoding is ambiguous because literal
    '-' chars collide with path-separator encoding, so we match on the TAIL of
    the encoded name with a strict regex instead of decoding.

    A project dir matches if its encoded name ends with one of:
      -{repo}                    (non-multi-clone, e.g. -home-alice-code-myrepo)
      -{repo}-\\d+                (flat clone: myrepo-0, myrepo-1, ...)
      -{repo}-w\\d+               (workspace root: myrepo-w0)
      -{repo}-w\\d+-c\\d+          (workspace clone: myrepo-w0-c2)
    """
    if not CLAUDE_PROJECTS.exists():
        return []

    tail_re = re.compile(
        rf"-{re.escape(repo)}(?:-(?:w\d+(?:-c\d+)?|\d+))?$"
    )

    matches: list[Path] = []
    for child in sorted(CLAUDE_PROJECTS.iterdir()):
        if not child.is_dir():
            continue
        if tail_re.search(child.name):
            matches.append(child)
    return matches


def clone_label(project_dir: Path, repo: str) -> str:
    """Short label identifying which clone this project dir represents.

    Example mappings (based on trailing encoded-path segment):
      repo='ccgm', project_dir=-Users-lem-code-ccgm-repos-ccgm-1   → 'ccgm-1'
      repo='ccgm', -Users-lem-code-ccgm-workspaces-ccgm-w0-c2      → 'ccgm-w0-c2'
      repo='ccgm', -Users-lem-code-ccgm                            → 'ccgm'

    Requires the canonical repo name to disambiguate (since encoded path names
    cannot be uniquely reversed when repo names contain hyphens).
    """
    name = project_dir.name
    pattern = re.compile(
        rf"-{re.escape(repo)}(-(?:w\d+(?:-c\d+)?|\d+))?$"
    )
    m = pattern.search(name)
    if m:
        return f"{repo}{m.group(1) or ''}"
    return name


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        repo = sys.argv[2] if len(sys.argv) > 2 else detect_repo()
        if not repo:
            print("repo_detect: could not detect repo from cwd", file=sys.stderr)
            sys.exit(1)
        for p in list_project_dirs(repo):
            print(f"{clone_label(p, repo)}\t{p}")
    else:
        repo = detect_repo()
        if repo:
            print(repo)
        else:
            print("(none)", file=sys.stderr)
            sys.exit(1)
