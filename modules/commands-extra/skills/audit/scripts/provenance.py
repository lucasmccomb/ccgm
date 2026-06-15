#!/usr/bin/env python3
"""
CCGM /audit provenance.py (Epic 3.4) — STDLIB ONLY.

Three capabilities in one script:

1. HEADER  — emit an audit_provenance record (type: "audit_provenance") with:
     commit           base SHA the audit ran against. Prefer --commit (pinned by
                      the coordinator at spine time); falls back to live
                      git -C <repo> rev-parse HEAD only when --commit is absent.
     rubric_version   version field from severity-rubric.json
     skill_version    version from the audit module.json (or DEFAULT_SKILL_VERSION)
     tool_versions    map of installed spine tools -> version string (absent tools omitted)
     model            placeholder; fill from --model / AUDIT_MODEL env var (default "unknown")
     optional_checks_ran  list (empty by default; caller may pass --optional-check repeatedly)

   Naming note: the spine already emits {"type":"provenance","tool":"ccgm-spine",...} for
   run-time bookkeeping.  The audit-level record uses type="audit_provenance" to remain
   unambiguous.  merge-findings.py routes "provenance" records first in output; the caller
   must prepend the audit_provenance header before findings.jsonl content (see SKILL.md).

2. CODEOWNERS  — parse the repo's CODEOWNERS file (checked in order:
   .github/CODEOWNERS, CODEOWNERS, docs/CODEOWNERS) and for each finding in --findings,
   set properties.owner to the matching owner(s) using last-match-wins, gitignore-style
   path glob semantics.  Findings with no match get no owner field (omit rather than null).

3. PER-PACKAGE  — given monorepo package roots (detected from pnpm-workspace.yaml /
   package.json workspaces, or supplied via --packages), set properties.package on each
   finding to the owning package dir and emit a per-package summary record:
     {"type":"package_summary","package":"<dir>","counts":{"critical":N,"high":N,...}}

CLI:
  provenance.py --findings <jsonl> --repo <root>
                [--rubric <path>]          default: ../schemas/severity-rubric.json relative to script
                [--output <file>]          default: stdout
                [--model <str>]            model identifier; also read from AUDIT_MODEL env var
                [--commit <sha>]           base SHA pinned by the coordinator (preferred over live HEAD)
                [--optional-check <id>]   may be repeated
                [--packages <dir> ...]    explicit package roots (repo-relative); may be repeated
                [--skip-tool-versions]    omit tool_versions from header (speeds up tests)

Output (valid JSONL):
  1. {"type":"audit_provenance", ...}  header record
  2. finding records with properties.owner and/or properties.package set (where applicable)
  3. non-finding records from --findings (provenance, coverage_gap, etc.) -- passed through
  4. {"type":"package_summary","package":"<rel>","counts":{...}}  one per detected package

Exit codes:
  0  success
  1  malformed input (bad JSONL, unreadable file, invalid --repo path)
  2  missing or invalid CLI arguments (handled by argparse before script logic runs)
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SKILL_VERSION = "1.0.0"

# Spine tools whose --version we query (must not run untrusted code against the repo)
_SPINE_TOOLS = [
    "gitleaks",
    "semgrep",
    "trivy",
    "knip",
    "eslint",
    "govulncheck",
    "bandit",
    "hadolint",
    "actionlint",
    "zizmor",
    "pinact",
    "squawk",
    "sqlfluff",
]

# Per-tool version flags (most tools use --version; a few differ)
_VERSION_FLAGS: dict = {
    "gitleaks":    ["version"],
    "knip":        ["--version"],
    "eslint":      ["--version"],
    "govulncheck": ["-version"],
    "bandit":      ["--version"],
    "hadolint":    ["--version"],
    "actionlint":  ["-version"],
    "zizmor":      ["--version"],
    "pinact":      ["--version"],
    "squawk":      ["--version"],
    "sqlfluff":    ["--version"],
    "semgrep":     ["--version"],
    "trivy":       ["--version"],
}

_VALID_SEVERITIES = ["critical", "high", "medium", "low", "info"]

# CODEOWNERS file locations in standard precedence order
_CODEOWNERS_LOCATIONS = [
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
]


# ---------------------------------------------------------------------------
# Rubric loading (version only)
# ---------------------------------------------------------------------------

def _load_rubric_version(rubric_path: Path) -> str:
    """
    Read the 'version' field from severity-rubric.json.
    Returns "unknown" if missing, unreadable, or field absent.
    """
    if not rubric_path.exists():
        return "unknown"
    try:
        with open(rubric_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return "unknown"
    if isinstance(data, dict):
        v = data.get("version")
        if isinstance(v, str) and v:
            return v
    return "unknown"


# ---------------------------------------------------------------------------
# Skill version loading
# ---------------------------------------------------------------------------

def _load_skill_version() -> str:
    """
    Read version from the audit module's module.json (commands-extra/module.json).
    The audit skill lives inside commands-extra/skills/audit/scripts/; module.json
    is three levels up from scripts/.
    Falls back to DEFAULT_SKILL_VERSION if not found or no version field.
    """
    script_dir = Path(__file__).parent
    # scripts/../../../module.json -> commands-extra/module.json
    candidate = (script_dir / ".." / ".." / ".." / "module.json").resolve()
    if candidate.exists():
        try:
            with open(candidate, encoding="utf-8") as fh:
                data = json.load(fh)
            v = data.get("version")
            if isinstance(v, str) and v:
                return v
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SKILL_VERSION


# ---------------------------------------------------------------------------
# git commit
# ---------------------------------------------------------------------------

def _get_commit(repo_root: Path) -> str:
    """
    Return HEAD SHA of the repo using git plumbing only.
    Returns "unknown" on failure.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if result.returncode == 0:
            sha = result.stdout.decode("utf-8", errors="replace").strip()
            if sha:
                return sha
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Tool version probing
# ---------------------------------------------------------------------------

def _probe_tool_version(tool: str) -> "str | None":
    """
    Query a single tool for its version string.
    Returns the first non-empty output line, or None on failure.
    NO repo path is passed; only --version flags are used.
    """
    flags = _VERSION_FLAGS.get(tool, ["--version"])
    try:
        result = subprocess.run(
            [tool] + flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
        output = result.stdout.decode("utf-8", errors="replace").strip()
        for line in output.splitlines():
            line = line.strip()
            if line:
                return line
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _collect_tool_versions(skip: bool = False) -> dict:
    """
    Probe each spine tool for its version string.
    Returns {tool: version_str} for tools present on PATH.
    If skip is True, returns {}.
    """
    if skip:
        return {}
    versions: dict = {}
    for tool in _SPINE_TOOLS:
        v = _probe_tool_version(tool)
        if v is not None:
            versions[tool] = v
    return versions


# ---------------------------------------------------------------------------
# CODEOWNERS parsing -- last-match-wins, gitignore-style globs
# ---------------------------------------------------------------------------

def _find_codeowners(repo_root: Path) -> "Path | None":
    """Return the first CODEOWNERS file found in standard precedence order."""
    for rel in _CODEOWNERS_LOCATIONS:
        p = repo_root / rel
        if p.exists():
            return p
    return None


def _parse_codeowners(codeowners_path: Path) -> "list[tuple[str, list[str]]]":
    """
    Parse CODEOWNERS into [(pattern, [owner, ...]), ...] in file order.
    Last-match-wins: caller should iterate in reverse when matching.
    """
    rules: list = []
    try:
        with open(codeowners_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                # Strip inline comments
                if "#" in line:
                    line = line[: line.index("#")]
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if not parts:
                    continue
                pattern = parts[0]
                owners = parts[1:]
                rules.append((pattern, owners))
    except OSError:
        pass
    return rules


def _fnmatch_with_doublestar(path: str, pattern: str) -> bool:
    """
    Minimal '**' aware matcher.  Splits pattern on '**' and builds a regex
    where '**' segments match anything including '/'.
    """
    parts = pattern.split("**")
    regex_parts = []
    for p in parts:
        # Escape the literal part, then un-escape our own wildcards
        escaped = re.escape(p).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        regex_parts.append(escaped)
    regex = ".*".join(regex_parts)
    try:
        return bool(re.fullmatch(regex, path))
    except re.error:
        return False


def _codeowners_match(path: str, pattern: str) -> bool:
    """
    Determine whether a repo-relative file path matches a CODEOWNERS pattern.

    Semantics (gitignore-style):
    - Trailing '/' matches the directory and everything under it.
    - Leading '/' anchors to the repo root.
    - Pattern with '/' in the middle matches relative to the repo root.
    - No '/' in the pattern (no leading, no middle): match against the basename.
    - '**' matches across directory separators.
    """
    path = path.replace("\\", "/").lstrip("/")

    if pattern.endswith("/"):
        prefix = pattern.rstrip("/").lstrip("/")
        return path.startswith(prefix + "/") or path == prefix

    if pattern.startswith("/"):
        anchored = pattern.lstrip("/")
        if "**" in anchored:
            return _fnmatch_with_doublestar(path, anchored)
        return fnmatch.fnmatchcase(path, anchored)

    if "/" in pattern:
        stripped = pattern.lstrip("/")
        if "**" in stripped:
            return _fnmatch_with_doublestar(path, stripped)
        # No glob metacharacters and no trailing slash: treat as directory prefix
        # (e.g. "apps/web" matches "apps/web/x.ts" and "apps/web" itself).
        if "*" not in stripped and "?" not in stripped:
            return path == stripped or path.startswith(stripped + "/")
        return fnmatch.fnmatchcase(path, stripped)

    # No slash: match basename anywhere in the tree
    basename = path.rsplit("/", 1)[-1] if "/" in path else path
    return fnmatch.fnmatchcase(basename, pattern)


def _tag_owners(findings: list, rules: list) -> None:
    """
    Tag each finding dict in-place with properties.owner.
    Last-match-wins: iterates rules in reverse order.
    """
    if not rules:
        return
    reversed_rules = list(reversed(rules))
    for f in findings:
        if "type" in f:
            continue
        path = (f.get("location") or {}).get("path", "")
        if not path:
            continue
        for pattern, owners in reversed_rules:
            if _codeowners_match(path, pattern):
                if owners:
                    props = dict(f.get("properties") or {})
                    props["owner"] = owners if len(owners) > 1 else owners[0]
                    f["properties"] = props
                break


# ---------------------------------------------------------------------------
# Per-package detection and tagging
# ---------------------------------------------------------------------------

def _parse_pnpm_workspace(path: Path) -> list:
    """
    Simple YAML parser for pnpm-workspace.yaml's 'packages:' list.
    Does NOT require PyYAML (STDLIB only).
    """
    patterns: list = []
    try:
        with open(path, encoding="utf-8") as fh:
            in_packages = False
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("packages:"):
                    in_packages = True
                    continue
                if in_packages:
                    if stripped.startswith("- "):
                        val = stripped[2:].strip().strip('"').strip("'")
                        if val:
                            patterns.append(val)
                    elif stripped and not stripped.startswith("#"):
                        in_packages = False
    except OSError:
        pass
    return patterns


def _expand_workspace_globs(repo_root: Path, patterns: list) -> list:
    """
    Expand workspace glob patterns into concrete repo-relative directory paths.
    Handles patterns like "packages/*", "apps/fe-*", "packages/auth".
    If a pattern contains a glob char (* or ?), always expand children; never
    add the static prefix directory itself.
    """
    results: list = []
    for pattern in patterns:
        pattern = pattern.rstrip("/")
        has_glob = "*" in pattern or "?" in pattern
        if not pattern:
            continue
        if has_glob:
            # Strip the trailing glob portion to find the parent directory
            # e.g. "packages/*"  -> parent_path="packages", name_glob="*"
            # e.g. "apps/fe-*"  -> parent_path="apps",     name_glob="fe-*"
            slash_pos = pattern.rfind("/")
            if slash_pos == -1:
                parent_rel = ""
                name_glob = pattern
            else:
                parent_rel = pattern[:slash_pos]
                name_glob = pattern[slash_pos + 1:]
            parent = repo_root / parent_rel if parent_rel else repo_root
            if parent.is_dir():
                for child in sorted(parent.iterdir()):
                    if child.is_dir() and fnmatch.fnmatchcase(child.name, name_glob):
                        results.append(str(child.relative_to(repo_root)))
        else:
            candidate = repo_root / pattern
            if candidate.is_dir():
                results.append(str(candidate.relative_to(repo_root)))
    return results


def _detect_packages(repo_root: Path) -> list:
    """
    Detect monorepo package roots from workspace config files.
    Returns repo-relative directory path strings.
    """
    packages: list = []

    pnpm_ws = repo_root / "pnpm-workspace.yaml"
    if pnpm_ws.exists():
        patterns = _parse_pnpm_workspace(pnpm_ws)
        packages.extend(_expand_workspace_globs(repo_root, patterns))
        if packages:
            return packages

    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json, encoding="utf-8") as fh:
                pkg = json.load(fh)
            ws = pkg.get("workspaces", [])
            if isinstance(ws, dict):
                ws = ws.get("packages", [])
            if isinstance(ws, list):
                packages.extend(_expand_workspace_globs(repo_root, ws))
        except (json.JSONDecodeError, OSError):
            pass

    return packages


def _tag_packages(findings: list, package_roots: list) -> None:
    """
    Tag each finding in-place with properties.package.
    Longest-prefix match wins (most-specific package).
    """
    if not package_roots:
        return
    sorted_roots = sorted(package_roots, key=len, reverse=True)
    for f in findings:
        if "type" in f:
            continue
        path = (f.get("location") or {}).get("path", "")
        if not path:
            continue
        path_norm = path.replace("\\", "/").lstrip("/")
        for root in sorted_roots:
            root_norm = root.replace("\\", "/").rstrip("/")
            if path_norm == root_norm or path_norm.startswith(root_norm + "/"):
                props = dict(f.get("properties") or {})
                props["package"] = root_norm
                f["properties"] = props
                break


def _build_package_summaries(findings: list) -> list:
    """Build per-package summary records from tagged findings."""
    counts: dict = {}
    for f in findings:
        if "type" in f:
            continue
        pkg = (f.get("properties") or {}).get("package")
        if not pkg:
            continue
        if pkg not in counts:
            counts[pkg] = {s: 0 for s in _VALID_SEVERITIES}
        sev = f.get("severity", "")
        if sev in counts[pkg]:
            counts[pkg][sev] += 1
        else:
            counts[pkg]["info"] += 1
    summaries = []
    for pkg, c in sorted(counts.items()):
        summaries.append({
            "type": "package_summary",
            "package": pkg,
            "counts": c,
        })
    return summaries


# ---------------------------------------------------------------------------
# JSONL loading
# ---------------------------------------------------------------------------

def _load_jsonl(path: str) -> "tuple[list, list]":
    """
    Load a JSONL file.  Returns (metadata_records, finding_records).
    metadata_records have a 'type' field; finding_records do not.
    Exits 1 with a clear error on IO or parse failure.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(f"provenance: ERROR: cannot read findings file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)

    metadata: list = []
    findings: list = []
    for lineno, raw in enumerate(raw_lines, 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"provenance: ERROR: findings line {lineno} is not valid JSON: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(obj, dict):
            print(
                f"provenance: ERROR: findings line {lineno} is not a JSON object",
                file=sys.stderr,
            )
            sys.exit(1)
        if "type" in obj:
            metadata.append(obj)
        else:
            findings.append(obj)
    return metadata, findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit audit_provenance header, tag CODEOWNERS owners, "
            "and add per-package scoping to audit findings."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--findings",
        required=True,
        metavar="PATH",
        help="Input findings JSONL (merge-findings output).",
    )
    parser.add_argument(
        "--repo",
        required=True,
        metavar="PATH",
        help="Absolute path to the repository root.",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        metavar="PATH",
        help="Path to severity-rubric.json (default: ../schemas/severity-rubric.json).",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write output JSONL to this file (default: stdout).",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="STR",
        help=(
            "Model identifier for this audit run. "
            "Also read from AUDIT_MODEL env var. Default: 'unknown'. "
            "Fill from the coordinator at runtime."
        ),
    )
    parser.add_argument(
        "--commit",
        default=None,
        metavar="SHA",
        help=(
            "Base commit SHA the audit actually ran against. The coordinator "
            "captures this ONCE at spine time (before any worktree/worker work) "
            "and passes it here. Without it, the header records the repo's LIVE "
            "HEAD, which a fix-mode worker that polluted the main checkout may "
            "have moved -- recording the wrong 'audited at' commit (field "
            "report #5). Falls back to `git -C <repo> rev-parse HEAD` if absent."
        ),
    )
    parser.add_argument(
        "--optional-check",
        action="append",
        default=[],
        metavar="ID",
        dest="optional_checks",
        help="Optional check that ran during this audit (may be repeated).",
    )
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Explicit package root (repo-relative, may be repeated). "
            "Disables auto-detection from workspace files."
        ),
    )
    parser.add_argument(
        "--skip-tool-versions",
        action="store_true",
        default=False,
        help="Skip tool-version probing (useful in tests).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(
            f"provenance: ERROR: --repo '{args.repo}' is not a directory",
            file=sys.stderr,
        )
        return 1

    # Resolve rubric path
    script_dir = Path(__file__).parent
    if args.rubric:
        rubric_path = Path(args.rubric).resolve()
    else:
        rubric_path = (script_dir / ".." / "schemas" / "severity-rubric.json").resolve()

    # Load input findings
    metadata_records, findings = _load_jsonl(args.findings)

    # Build the audit_provenance header
    model = args.model or os.environ.get("AUDIT_MODEL", "unknown")
    rubric_version = _load_rubric_version(rubric_path)
    skill_version = _load_skill_version()
    # Prefer the coordinator-pinned base SHA over live HEAD (#5): a polluting
    # fix-mode worker can move the main checkout's HEAD, so reading it here
    # would record the wrong commit.
    commit = args.commit or _get_commit(repo_root)
    tool_versions = _collect_tool_versions(skip=args.skip_tool_versions)

    header: dict = {
        "type": "audit_provenance",
        "commit": commit,
        "rubric_version": rubric_version,
        "skill_version": skill_version,
        "tool_versions": tool_versions,
        "model": model,
        "optional_checks_ran": args.optional_checks,
    }

    # CODEOWNERS tagging
    codeowners_path = _find_codeowners(repo_root)
    if codeowners_path is not None:
        rules = _parse_codeowners(codeowners_path)
        _tag_owners(findings, rules)

    # Per-package tagging
    if args.packages:
        package_roots = args.packages
    else:
        package_roots = _detect_packages(repo_root)

    if package_roots:
        _tag_packages(findings, package_roots)

    package_summaries = _build_package_summaries(findings)

    # Build output lines
    output_lines: list = []
    # 1. audit_provenance header first
    output_lines.append(json.dumps(header, separators=(",", ":")))
    # 2. Tagged findings
    for f in findings:
        output_lines.append(json.dumps(f, separators=(",", ":")))
    # 3. Metadata passthrough (provenance, coverage_gap, etc.)
    for rec in metadata_records:
        output_lines.append(json.dumps(rec, separators=(",", ":")))
    # 4. Per-package summaries
    for rec in package_summaries:
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
            print(f"provenance: ERROR: cannot write output: {exc}", file=sys.stderr)
            return 1
        print(
            f"provenance: wrote header + {len(findings)} finding(s) + "
            f"{len(package_summaries)} package-summary record(s) to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
