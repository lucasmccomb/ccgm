#!/usr/bin/env python3
"""
CCGM audit spine -- shared path-exclusion helpers (STDLIB ONLY).

Single source of truth:
  - excluded directory NAMES   -> `exclude-dirs.txt`      (same directory)
  - excluded file-name GLOBS   -> `exclude-file-globs.txt` (same directory)

This module reads those files and provides:

  Library:
    load_excluded_dirs()       -> list[str]   canonical excluded dir names
    load_excluded_file_globs() -> list[str]   canonical excluded file globs
    path_is_excluded(path)     -> bool        True if any path SEGMENT is an
                                              excluded dir OR the basename
                                              matches an excluded file glob

  CLI:
    exclude.py --gitleaks-config <out> [<repo>]
        Write a gitleaks v8 config that keeps the default ruleset
        ([extend] useDefault = true) but allowlists, by path regex:
          - every excluded dir + file glob (vendored/generated/worktree), and
          - when <repo> is a git repo, every GITIGNORED path. A "leaked
            credential" describes committed/tracked content; a gitignored,
            never-committed file like .env.local must not be reported as one.

    exclude.py --filter <in.jsonl> <out.jsonl> [<repo>]
        Coordinator-side junk-path post-filter (defense-in-depth, #1).
        Drops FINDING records whose location.path contains an excluded
        segment, matches an excluded file glob, or -- when <repo> is given --
        is gitignored. Passes through every record with a "type" field
        (provenance, coverage_gap, skipped) untouched. Prints a one-line
        summary to stderr: "filter-excluded: dropped N junk-path finding(s)".

The wrappers that walk the filesystem also apply per-tool exclusion flags
(built from the same lists by exclude.sh) so the tools never SCAN the junk
paths in the first place -- that is the performance fix. This filter is the
correctness backstop that catches anything a tool's own ignore logic misses.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_EXCLUDE_LIST = os.path.join(_SCRIPT_DIR, "exclude-dirs.txt")
_EXCLUDE_GLOBS = os.path.join(_SCRIPT_DIR, "exclude-file-globs.txt")


def _read_list(path):
    """Read a list file (one entry per line; # comments and blanks ignored)."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].strip()
                if line:
                    out.append(line)
    except OSError:
        return None
    return out


def load_excluded_dirs():
    """Return the canonical excluded directory names from exclude-dirs.txt."""
    dirs = _read_list(_EXCLUDE_LIST)
    if dirs is None:
        # Fall back to a hard-coded minimal set so the filter never silently
        # becomes a no-op if the list file is missing.
        dirs = ["node_modules", ".git", ".claude", ".audit", "dist", "build"]
    return dirs


def load_excluded_file_globs():
    """Return the canonical excluded file globs from exclude-file-globs.txt."""
    globs = _read_list(_EXCLUDE_GLOBS)
    if globs is None:
        globs = ["*.min.js", "*.min.css", "*.bundle.js"]
    return globs


def _build_segment_matcher(dirs):
    """Compile a regex matching any path that contains an excluded segment."""
    alts = "|".join(re.escape(d) for d in dirs)
    # A segment is bounded by start/slash on the left and slash/end on the right.
    return re.compile(r"(^|/)(" + alts + r")(/|$)")


_EXCLUDED_DIRS = load_excluded_dirs()
_EXCLUDED_FILE_GLOBS = load_excluded_file_globs()
_SEGMENT_RE = _build_segment_matcher(_EXCLUDED_DIRS)


def path_is_excluded(path):
    """True if any segment of `path` is an excluded directory name, or the
    basename matches an excluded file glob."""
    if not path:
        return False
    normalized = str(path).replace("\\", "/")
    if _SEGMENT_RE.search(normalized):
        return True
    base = normalized.rsplit("/", 1)[-1]
    for glob in _EXCLUDED_FILE_GLOBS:
        if fnmatch.fnmatch(base, glob):
            return True
    return False


# ---------------------------------------------------------------------------
# Gitignore awareness
# ---------------------------------------------------------------------------

def gitignored_entries(repo):
    """Return repo-relative gitignored paths, or [] when `repo` is not a git
    repo / git is unavailable.

    Uses `--directory` so a fully-ignored directory collapses to a single
    entry (e.g. "node_modules/") instead of every file underneath it -- keeps
    the list small on real repos. Directory entries keep their trailing slash.
    """
    if not repo or not os.path.isdir(repo):
        return []
    try:
        proc = subprocess.run(
            [
                "git", "-C", repo, "ls-files", "-z",
                "--others", "--ignored", "--exclude-standard", "--directory",
                "--", ".",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    raw = proc.stdout.decode("utf-8", "replace")
    return [e for e in raw.split("\0") if e]


# ---------------------------------------------------------------------------
# Looks-minified heuristic
# ---------------------------------------------------------------------------

# A line longer than this in the file's leading bytes marks it as machine-
# generated/minified. Real hand-written source rarely exceeds a few hundred
# chars; vendored bundles like js-dos run to 100k+ char lines.
_MINIFIED_MAX_LINE = 1000
_MINIFIED_READ_BYTES = 262144  # inspect only the first 256 KB


def looks_minified(abs_path, cache):
    """True if the file at abs_path looks machine-minified (a very long line in
    its leading bytes). Memoized via the caller-supplied `cache` dict so a file
    with hundreds of findings is read once."""
    if abs_path in cache:
        return cache[abs_path]
    result = False
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            chunk = fh.read(_MINIFIED_READ_BYTES)
        for line in chunk.split("\n"):
            if len(line) >= _MINIFIED_MAX_LINE:
                result = True
                break
    except OSError:
        result = False
    cache[abs_path] = result
    return result


def _path_is_gitignored(path, entries):
    """True if `path` equals or sits under any gitignored entry."""
    if not path:
        return False
    p = str(path).replace("\\", "/").lstrip("./")
    for e in entries:
        clean = e.rstrip("/")
        if not clean:
            continue
        if e.endswith("/"):
            if p == clean or p.startswith(clean + "/"):
                return True
        elif p == clean:
            return True
    return False


# ---------------------------------------------------------------------------
# CLI: gitleaks config
# ---------------------------------------------------------------------------

def _regex_escape_path(path):
    """Escape a repo-relative path into a literal RE2 sub-pattern (slashes kept)."""
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", path)


def _glob_to_basename_regex(glob):
    """Convert a simple basename glob (e.g. *.min.js) into an RE2 sub-pattern.
    `*` -> any run of non-slash chars, `?` -> one non-slash char, all else
    literal. Avoids fnmatch.translate, whose (?s:...)\\Z wrapper is not a
    valid embeddable RE2 fragment."""
    out = []
    for ch in glob:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _gitleaks_allowlist_paths(repo):
    """Build the list of allowlist path regexes for the gitleaks config."""
    paths = []
    # Excluded directories: match the dir anywhere in the path.
    for d in load_excluded_dirs():
        paths.append("(^|/){0}(/|$)".format(_regex_escape_path(d)))
    # Excluded file globs: match the basename at the end of the path.
    for glob in load_excluded_file_globs():
        paths.append("(^|/){0}$".format(_glob_to_basename_regex(glob)))
    # Gitignored paths: a leaked credential must be committed/tracked, never a
    # gitignored local file (e.g. .env.local). Skip ones already covered above.
    for e in gitignored_entries(repo):
        clean = e.rstrip("/")
        if not clean or path_is_excluded(clean):
            continue
        esc = _regex_escape_path(clean)
        if e.endswith("/"):
            paths.append("(^|/){0}(/|$)".format(esc))
        else:
            paths.append("(^|/){0}$".format(esc))
    return paths


def _write_gitleaks_config(out_path, repo=None):
    lines = [
        "# Auto-generated by exclude.py from exclude-dirs.txt + exclude-file-globs.txt.",
        "# Do not edit by hand. Keeps gitleaks' default ruleset; allowlists",
        "# vendored/generated/worktree paths and gitignored (never-committed) files.",
        "[extend]",
        "useDefault = true",
        "",
        "[allowlist]",
        'description = "skip vendored/generated/worktree/gitignored paths (CCGM audit spine)"',
        "paths = [",
    ]
    for pat in _gitleaks_allowlist_paths(repo):
        # Triple-quoted TOML string so backslashes are literal (no escaping).
        lines.append("    '''{0}''',".format(pat))
    lines.append("]")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI: JSONL junk-path filter
# ---------------------------------------------------------------------------

def _filter_jsonl(in_path, out_path, repo=None):
    dropped = 0
    kept = 0
    entries = gitignored_entries(repo) if repo else []
    minified_cache = {}
    with open(in_path, encoding="utf-8") as fin, \
            open(out_path, "w", encoding="utf-8") as fout:
        for raw in fin:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                # Pass through malformed lines untouched -- not our job to drop.
                fout.write(stripped + "\n")
                continue
            # Records with a "type" field (provenance, coverage_gap, skipped)
            # always pass through; they have no location to judge.
            if isinstance(rec, dict) and "type" not in rec:
                path = (rec.get("location") or {}).get("path", "")
                drop = path_is_excluded(path) or _path_is_gitignored(path, entries)
                # Looks-minified backstop: drop findings on vendored/minified files
                # that no name/dir rule caught (e.g. client/public/js-dos/js-dos.js
                # -- minified but not *.min.js, not in an excluded dir). Minified
                # bundles are generated/vendored, not authored source, so lint and
                # code-pattern (SAST) findings there are noise. SECRETS are kept: a
                # committed credential is actionable regardless of minification.
                # Needs repo to resolve the relative path to file content.
                if not drop and repo and path \
                        and not str(rec.get("check_id", "")).startswith("secrets/"):
                    abs_path = os.path.join(repo, path)
                    if looks_minified(abs_path, minified_cache):
                        drop = True
                if drop:
                    dropped += 1
                    continue
                kept += 1
            fout.write(stripped + "\n")
    print(
        "filter-excluded: dropped {0} junk-path finding(s), kept {1}".format(
            dropped, kept
        ),
        file=sys.stderr,
    )
    return dropped


def main(argv):
    if len(argv) >= 3 and argv[1] == "--gitleaks-config":
        repo = argv[3] if len(argv) >= 4 else None
        _write_gitleaks_config(argv[2], repo)
        return 0
    if len(argv) >= 4 and argv[1] == "--filter":
        repo = argv[4] if len(argv) >= 5 else None
        _filter_jsonl(argv[2], argv[3], repo)
        return 0
    sys.stderr.write(
        "Usage:\n"
        "  exclude.py --gitleaks-config <out.toml> [<repo>]\n"
        "  exclude.py --filter <in.jsonl> <out.jsonl> [<repo>]\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
