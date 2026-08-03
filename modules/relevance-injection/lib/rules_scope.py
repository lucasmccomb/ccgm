#!/usr/bin/env python3
"""Generate a repo's `claudeMdExcludes` block (plan.md Epic 0.5, issue #952).

WHAT THIS DOES
--------------
Inspects a target repo, decides which INSTALLED CCGM rule files are
irrelevant to it, and proposes (or, with --write, applies) a
`claudeMdExcludes` array in that repo's `.claude/settings.json`. This turns
a per-machine hand-edit into a generated, reviewable, committable artifact
-- Claude Code's own `claudeMdExcludes` settings key already suppresses a
user-level `~/.claude/rules/*.md` file from loading when a project-layer
`.claude/settings.json` names it (verified empirically -- see "PATH
RESOLUTION" below for the specific gotcha that verification surfaced).

Dry run by default. Nothing is written unless --write is passed.

WHY THIS EXISTS (plan.md Epic 0.5)
-----------------------------------
`claudeMdExcludes` was recorded as a rejected alternative through six plan
reviews because a hand-edited, per-machine settings file "is not a
shippable product answer." Testing it found that objection only holds for
a HAND-edited file -- a GENERATED one is exactly as shippable as any other
CCGM artifact. This script is that generator. It is deliberately
independent of Epic 2's (deferred) per-rule-file tier/stakes taxonomy: it
falls back to (a) the manifest's existing `category: "tech-specific"` field
for repo-profile-gated exclusion, and (b) a small, conservative, hand-picked
list for repo-profile-INDEPENDENT "niche CCGM workflow" exclusion.

SAFETY RULES (enforced here AND by tests/test_rules_scope.py)
---------------------------------------------------------------
1. NEVER propose excluding a PINNED_FLOOR module's rules. PINNED_FLOOR is
   derived from `relevance_select.safety_core_modules()` (the seven
   SAFETY_CORE_TIERS modules) plus the same four additional pinned names
   plan.md section 3.3 names -- imported/derived from one place, not
   re-typed, so this list can never quietly drift from the platform's own
   safety-core definition.
2. NEVER write outside the target repo's `.claude/settings.json`, and
   MERGE rather than overwrite: an existing `claudeMdExcludes` array is
   extended and every other key in the file is preserved.
3. Dry run by default; `--write` is required to modify anything.

PATH RESOLUTION -- a load-bearing empirical finding
----------------------------------------------------
`claudeMdExcludes` matches against the REAL, symlink-resolved path of the
loaded instruction file -- NOT the `~/.claude/rules/<file>.md` symlink path
CCGM's installer creates under `linkMode`. This was verified directly
(2026-08-03, headless `claude -p`, project-level `.claude/settings.json`,
the `InstructionsLoaded` hook as the oracle -- same technique the Epic 0.5
experiment and Epic 7 used):

  - excluding `~/.claude/rules/mcp-development.md` (the symlink path,
    absolute or `~`-relative) did NOT suppress loading -- the file still
    appeared in the InstructionsLoaded log, correctly recorded at its
    real path `/Users/x/code/ccgm/modules/mcp-development/rules/mcp-development.md`.
  - excluding that REAL, resolved path DID suppress it (46 records
    instead of 47; the file was absent; every other rule still loaded).

So every path this module writes into `claudeMdExcludes` is
`os.path.realpath()` of the installed location. Under `linkMode` that
resolves to the canonical repo file; under a `--copy` install (no
symlink), `realpath()` of a plain file is the file itself -- so this one
code path is correct in both install modes without a branch.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import relevance_select  # noqa: E402 -- reuse the existing pure helpers


# ---------------------------------------------------------------------------
# PINNED_FLOOR -- the single source of truth for "never propose excluding
# this module's rules." plan.md's intended future home for this constant
# is Epic 3's lib/rule_tiering.py (deferred, not built in this epic); until
# that lands, THIS is authoritative for the exclusion tool and should be
# imported from here rather than re-typed. Derived, not hardcoded twice:
# the safety-core half comes straight from relevance_select.safety_core_modules(),
# so the two lists can never silently drift apart.
# ---------------------------------------------------------------------------
PINNED_FLOOR: "tuple[str, ...]" = tuple(relevance_select.safety_core_modules()) + (
    "identity",
    "live-testing-guard",
    "git-worktrees",
    "model-vetting",
    "branch-guard",
)

TECH_SPECIFIC_CATEGORY = "tech-specific"

# Conservative, hand-picked fallback for Epic 2's not-yet-existing per-rule-
# file tier/stakes taxonomy (this epic's own "Inputs" contract: use Epic 2's
# assignment if it exists, else fall back to a conservative built-in list).
# Maps module name -> None (propose every rule file the module ships) or a
# set of specific module-relative rule targets (propose only that subset).
#
# Deliberately narrow and NOT repo-profile-gated: these are rules about a
# specific CCGM meta-workflow (a nightly pipeline, a visual-convergence
# loop, SSH to a configured remote box, ...) that is rarely in play
# regardless of the target repo's tech stack, so detecting relevance from
# repo files does not apply the way it does for the tech-specific category.
#
# `self-improving` ships TWO rule files and only one is listed: its other
# file, `rules/learnings-store.md`, is explicitly `high` stakes in the
# plan's own tier-assignment work (a destructive-git-operation risk), so it
# is never proposed here even though its sibling file in the same module
# is a safe, ordinary "index"-shaped rule. Modules omitted from this dict
# entirely are simply never proposed by this category -- always the safe
# direction, since it can only under-propose, never over-propose.
NICHE_MODULE_RULE_TARGETS: "dict[str, set[str] | None]" = {
    "agent-native": None,
    "argus": None,
    "autoheal": None,
    "browser-automation": None,
    "dreaming": None,
    "multi-agent": None,
    "remote-server": None,
    "self-improving": {"rules/self-improving.md"},
    "youtube-transcripts": None,
}

# Directories a repo-profile walk should never descend into: build output,
# dependency caches, and VCS metadata. Also skips any dot-directory.
_SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", "target", "out",
    "venv", ".venv", "__pycache__", "coverage",
}
_MAX_WALK_DEPTH = 4


def _walk(repo_path: str):
    """Yield (dirpath, dirnames, filenames) under `repo_path`, pruning
    heavy/irrelevant directories and bounding depth so this can never
    become an accidental full-disk walk on a large or deeply nested repo.
    `dirnames` is pruned in place (the `os.walk` topdown contract), so
    callers see the same pruned view this function used internally.
    """
    repo_path = os.path.abspath(repo_path)
    base_depth = repo_path.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(repo_path):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        if depth >= _MAX_WALK_DEPTH - 1:
            dirnames[:] = []
        yield dirpath, dirnames, filenames


def _has_file_matching(repo_path: str, patterns: "list[str]") -> bool:
    """True if any file under `repo_path` matches any of `patterns`
    (fnmatch-style, e.g. "tailwind.config.*")."""
    for _dirpath, _dirnames, filenames in _walk(repo_path):
        for fname in filenames:
            if any(fnmatch.fnmatch(fname, pat) for pat in patterns):
                return True
    return False


def _has_dir_named(repo_path: str, names: "list[str]") -> bool:
    """True if any directory under `repo_path` is named exactly one of `names`."""
    wanted = set(names)
    for _dirpath, dirnames, _filenames in _walk(repo_path):
        if wanted & set(dirnames):
            return True
    return False


def _package_json_dependency_names(path: str) -> "set[str]":
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    names: "set[str]" = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.update(section.keys())
    return names


def _has_dependency_substring(repo_path: str, substrings: "list[str]") -> bool:
    """True if any package.json under `repo_path` declares a dependency
    whose name contains one of `substrings` (case-insensitive)."""
    needles = [s.lower() for s in substrings]
    for dirpath, _dirnames, filenames in _walk(repo_path):
        if "package.json" not in filenames:
            continue
        for dep in _package_json_dependency_names(os.path.join(dirpath, "package.json")):
            dep_l = dep.lower()
            if any(n in dep_l for n in needles):
                return True
    return False


def _text_file_contains(repo_path: str, filenames: "set[str]", substrings: "list[str]") -> bool:
    """True if any file under `repo_path` named one of `filenames` contains
    (case-insensitive) any of `substrings`. Used for Python-ecosystem
    manifests (requirements.txt, pyproject.toml) that have no single
    canonical dependency schema the way package.json does."""
    needles = [s.lower() for s in substrings]
    for dirpath, _dirnames, fnames in _walk(repo_path):
        for fname in fnames:
            if fname not in filenames:
                continue
            try:
                with open(os.path.join(dirpath, fname), encoding="utf-8", errors="ignore") as fh:
                    text = fh.read().lower()
            except OSError:
                continue
            if any(n in text for n in needles):
                return True
    return False


_PY_DEP_FILES = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"}


def detect_repo_profile(repo_path: str) -> "dict[str, bool]":
    """Inspect `repo_path` for signals that a tech-specific CCGM module's
    rules are relevant to it. Returns {module_name: bool}; True means "this
    module's rules apply here -- do not propose excluding them."

    Bounded, read-only filesystem inspection only (module.json's declared
    `category: "tech-specific"` set drives which module names appear here
    -- see propose_excludes()). A repo this cannot positively identify
    (e.g. a bare Rust crate with no web/backend markers at all) yields
    every entry False, which is the conservative-toward-EXCLUSION direction
    for this category -- the opposite of PINNED_FLOOR's conservative-
    toward-INCLUSION default, and deliberately so: this category exists
    specifically to identify genuinely-irrelevant tech-specific rules.
    """
    tailwind = _has_file_matching(repo_path, ["tailwind.config.*"]) or _has_dependency_substring(
        repo_path, ["tailwindcss"]
    )
    shadcn = _has_file_matching(repo_path, ["components.json"]) or _has_dependency_substring(
        repo_path, ["shadcn"]
    )
    supabase = (
        _has_dir_named(repo_path, ["supabase"])
        or _has_dependency_substring(repo_path, ["supabase"])
        or _text_file_contains(repo_path, _PY_DEP_FILES, ["supabase"])
    )
    cloudflare = _has_file_matching(
        repo_path, ["wrangler.toml", "wrangler.json", "wrangler.jsonc"]
    ) or _has_dependency_substring(repo_path, ["wrangler", "cloudflare"])
    mcp_development = (
        _has_file_matching(repo_path, [".mcp.json", "mcp.json"])
        or _has_dependency_substring(repo_path, ["@modelcontextprotocol/sdk", "fastmcp"])
        or _text_file_contains(repo_path, _PY_DEP_FILES, ["fastmcp", "modelcontextprotocol"])
    )
    return {
        "tailwind": tailwind,
        "shadcn": shadcn,
        "supabase": supabase,
        "cloudflare": cloudflare,
        "mcp-development": mcp_development,
    }


def _resolved_rule_path(target: str, home: str) -> str:
    """Resolve a module-relative rule target (e.g. "rules/tailwind.md") to
    the REAL, symlink-resolved absolute path Claude Code actually loads.
    See the module docstring's "PATH RESOLUTION" section for why this
    matters -- the `~/.claude/rules/<file>.md` symlink path itself does
    NOT work as a `claudeMdExcludes` entry.
    """
    installed = os.path.join(home, ".claude", target)
    return os.path.realpath(installed)


def propose_excludes(
    repo_profile: "dict[str, bool]",
    modules_dir: str,
    installed_modules: "list[str]",
    home: "str | None" = None,
) -> "list[dict]":
    """Return the sorted list of exclude-candidate rows.

    Each row: {"module", "rule" (module-relative target), "category"
    ("tech-specific" or "niche"), "path" (the resolved absolute path to
    put in claudeMdExcludes)}.

    Never includes a PINNED_FLOOR module (checked explicitly here, in
    addition to being true by construction of the two candidate sets
    below -- belt and suspenders per this epic's own safety-rules
    contract). Never includes a module absent from `installed_modules`.
    """
    home = home or os.path.expanduser("~")
    installed = set(installed_modules)
    rows: "list[dict]" = []

    # --- Category 1: tech-specific, repo-profile-gated -----------------
    for module in sorted(installed):
        if module in PINNED_FLOOR:
            continue
        manifest = relevance_select.read_module_manifest(modules_dir, module)
        if not manifest or manifest.get("category") != TECH_SPECIFIC_CATEGORY:
            continue
        if repo_profile.get(module, False):
            continue  # detected as relevant in this repo -- keep it loaded
        for target in relevance_select.rule_files_for_module(manifest):
            rows.append(
                {
                    "module": module,
                    "rule": target,
                    "category": "tech-specific",
                    "path": _resolved_rule_path(target, home),
                }
            )

    # --- Category 2: niche CCGM workflow, NOT repo-profile-gated -------
    for module in sorted(NICHE_MODULE_RULE_TARGETS):
        if module in PINNED_FLOOR or module not in installed:
            continue
        manifest = relevance_select.read_module_manifest(modules_dir, module)
        if not manifest:
            continue
        subset = NICHE_MODULE_RULE_TARGETS[module]
        all_targets = relevance_select.rule_files_for_module(manifest)
        targets = all_targets if subset is None else [t for t in all_targets if t in subset]
        for target in targets:
            rows.append(
                {
                    "module": module,
                    "rule": target,
                    "category": "niche",
                    "path": _resolved_rule_path(target, home),
                }
            )

    rows.sort(key=lambda r: (r["module"], r["rule"]))
    return rows


def write_settings(settings_path: str, exclude_paths: "list[str]") -> dict:
    """Merge `exclude_paths` into `settings_path`'s `claudeMdExcludes`
    array, creating the file (and its parent directory) if missing.

    Preserves every other top-level key untouched. Deterministic and
    idempotent: calling this twice with the same `exclude_paths` produces
    a byte-identical file (sorted keys, sorted/deduplicated excludes list).

    Raises ValueError if `settings_path` exists but is not a JSON object --
    refusing to guess is safer than silently clobbering a hand-edited file.

    MACHINE-SCOPED OUTPUT -- read before committing this file. Every path
    this writes is the ABSOLUTE, machine-specific real path resolved by
    `_resolved_rule_path()` at generation time (this machine's `ccgmRoot`,
    realpath-resolved). If `<repo>/.claude/settings.json` is committed and
    pulled onto a different machine -- a teammate, or the same operator with
    a different `ccgmRoot` -- none of the absolute paths will match that
    machine's own installed rule files. The failure direction is safe: a
    path that resolves to nothing simply does not match anything Claude Code
    loads, so every "excluded" rule silently LOADS again for that user rather
    than some other rule being wrongly dropped. This generator does not
    detect or warn about that mismatch at write time; regenerating with
    `/rules-scope --write` on the second machine re-resolves the paths
    correctly. A relative or environment-variable-templated path form would
    remove this footgun if Claude Code's `claudeMdExcludes` supports one --
    that has not been tested here, and building it is a design change beyond
    this fix's scope.
    """
    existing: dict = {}
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as fh:
            text = fh.read()
        if text.strip():
            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise ValueError(
                    f"{settings_path} exists but is not valid JSON; refusing to "
                    f"overwrite it: {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"{settings_path} does not contain a JSON object at the top level"
                )
            existing = parsed

    current = existing.get("claudeMdExcludes")
    current_list = list(current) if isinstance(current, list) else []
    existing["claudeMdExcludes"] = sorted(set(current_list) | set(exclude_paths))

    parent = os.path.dirname(settings_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Write atomically: tempfile in the same directory, then os.replace().
    #
    # open(path, "w") truncates to zero bytes AT OPEN TIME, before any content
    # is written. An interrupt between the open and the close -- Ctrl-C, an OOM
    # kill, a full disk -- would leave the user's settings.json empty or
    # half-written, destroying every pre-existing key: hook registrations,
    # permission rules, a hand-maintained claudeMdExcludes. This function's
    # whole contract is to merge into that file without disturbing anything
    # else, so losing it on a crash is the one failure it must not have.
    #
    # os.replace() is atomic within a filesystem, and the tempfile is created
    # alongside the target so the rename never crosses a device boundary. Same
    # pattern as modules/dreaming/lib/dream_analyze.py::_write_json_atomic.
    fd, tmp_path = tempfile.mkstemp(
        dir=parent or ".", prefix=".settings-", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(existing, indent=2, sort_keys=True))
            fh.write("\n")
        os.replace(tmp_path, settings_path)
    except BaseException:
        # Leave the original untouched on any failure, KeyboardInterrupt included.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return existing


# ---------------------------------------------------------------------------
# CLI wiring -- I/O only; every function above is importable and testable
# without a real ~/.claude install.
# ---------------------------------------------------------------------------
def _default_manifest_path() -> str:
    return os.path.expanduser("~/.claude/.ccgm-manifest.json")


def _load_manifest(path: str) -> "dict | None":
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _token_estimate(path: str) -> int:
    try:
        with open(path, "rb") as fh:
            return len(fh.read()) // 4
    except OSError:
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Propose (and, with --write, apply) a claudeMdExcludes block for a "
            "repo's installed-but-irrelevant CCGM rules (plan.md Epic 0.5)."
        )
    )
    p.add_argument("repo_path", nargs="?", default=".", help="Repo to scope (default: cwd)")
    p.add_argument(
        "--write",
        action="store_true",
        help="Write the proposal into <repo>/.claude/settings.json. Default is a dry run.",
    )
    p.add_argument(
        "--manifest",
        default=None,
        help="Override path to the installed CCGM manifest (mainly for testing).",
    )
    return p


def main(argv: "list[str] | None" = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_path = os.path.abspath(args.repo_path)

    manifest_path = args.manifest or _default_manifest_path()
    manifest = _load_manifest(manifest_path)
    if not manifest:
        print(f"No installed CCGM manifest found at {manifest_path}. Nothing to scope.")
        return 1

    ccgm_root = manifest.get("ccgmRoot")
    installed_modules = manifest.get("modules")
    if not isinstance(ccgm_root, str) or not ccgm_root or not isinstance(installed_modules, list):
        print(f"{manifest_path} is missing 'ccgmRoot' or 'modules'; cannot proceed.")
        return 1

    modules_dir = os.path.join(ccgm_root, "modules")
    profile = detect_repo_profile(repo_path)
    proposed = propose_excludes(profile, modules_dir, installed_modules)

    if not proposed:
        print(f"No exclusion candidates found for {repo_path}.")
        return 0

    print(f"Proposed claudeMdExcludes for {repo_path}:\n")
    header = f"{'MODULE':<20} {'CATEGORY':<14} {'RULE':<40} TOKENS"
    print(header)
    total_tokens = 0
    for row in proposed:
        tokens = _token_estimate(row["path"])
        total_tokens += tokens
        print(f"{row['module']:<20} {row['category']:<14} {row['rule']:<40} {tokens}")
    print(f"\n{len(proposed)} rule file(s), ~{total_tokens} tokens.")

    if not args.write:
        print("\nDry run -- nothing written. Re-run with --write to apply.")
        return 0

    settings_path = os.path.join(repo_path, ".claude", "settings.json")
    write_settings(settings_path, [row["path"] for row in proposed])
    print(f"\nWrote {len(proposed)} exclude(s) to {settings_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
