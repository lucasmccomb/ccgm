#!/usr/bin/env bash
set -euo pipefail

# CCGM Module Validation Tests
# Validates all modules have correct structure and metadata

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()

# Per-assertion PASS lines run into the thousands and, under heavy stdout on
# the macOS CI runner, a signal can interrupt a write mid-flush and surface as
# "echo: write error: Interrupted system call" (EINTR), failing the run
# spuriously. By default we stay quiet on success and only print failures plus
# the final summary, which keeps total writes small. Set VERBOSE=1 for the old
# per-assertion PASS output (used for local debugging).
VERBOSE="${VERBOSE:-0}"

# --- Helpers ---
pass() {
  PASS=$((PASS + 1))
  [ "$VERBOSE" = "1" ] && echo "  PASS: $1"
  return 0
}

fail() {
  FAIL=$((FAIL + 1))
  ERRORS+=("$1")
  echo "  FAIL: $1"
}

# Valid categories and scopes
VALID_CATEGORIES="core workflow commands patterns tech-specific"
VALID_SCOPES="global project"

# --- Check jq is available ---
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for module validation"
  echo "  Install: brew install jq (macOS) or apt install jq (Linux)"
  exit 1
fi

echo "=== CCGM Module Validation ==="
echo ""

# --- Test: Every modules/* directory has a module.json ---
echo "--- Checking module directories ---"
module_count=0
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  module_count=$((module_count + 1))

  if [ -f "$mod_dir/module.json" ]; then
    pass "$mod_name has module.json"
  else
    fail "$mod_name is missing module.json"
  fi
done
echo ""
echo "  Found $module_count modules"
echo ""

# --- Test: Each module.json is valid JSON ---
echo "--- Validating JSON syntax ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue

  if jq empty "$manifest" 2>/dev/null; then
    pass "$mod_name: valid JSON"
  else
    fail "$mod_name: invalid JSON in module.json"
  fi
done
echo ""

# --- Test: Required fields exist ---
echo "--- Checking required fields ---"
REQUIRED_FIELDS="name displayName description category scope files"

for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  # Skip invalid JSON
  jq empty "$manifest" 2>/dev/null || continue

  for field in $REQUIRED_FIELDS; do
    has_field=$(jq --arg f "$field" 'has($f)' "$manifest" 2>/dev/null)
    if [ "$has_field" = "true" ]; then
      pass "$mod_name: has '$field' field"
    else
      fail "$mod_name: missing required field '$field'"
    fi
  done
done
echo ""

# --- Test: name matches directory name ---
echo "--- Checking name/directory match ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  json_name=$(jq -r '.name' "$manifest" 2>/dev/null)
  if [ "$json_name" = "$mod_name" ]; then
    pass "$mod_name: name matches directory"
  else
    fail "$mod_name: name mismatch (json='$json_name', dir='$mod_name')"
  fi
done
echo ""

# --- Test: category is valid ---
echo "--- Checking categories ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  category=$(jq -r '.category // ""' "$manifest" 2>/dev/null)
  valid=false
  for vc in $VALID_CATEGORIES; do
    if [ "$category" = "$vc" ]; then
      valid=true
      break
    fi
  done

  if [ "$valid" = true ]; then
    pass "$mod_name: valid category '$category'"
  else
    fail "$mod_name: invalid category '$category' (expected one of: $VALID_CATEGORIES)"
  fi
done
echo ""

# --- Test: scope is valid array of global/project ---
echo "--- Checking scopes ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  # scope must be an array
  scope_type=$(jq -r '.scope | type' "$manifest" 2>/dev/null)
  if [ "$scope_type" != "array" ]; then
    fail "$mod_name: scope must be an array, got '$scope_type'"
    continue
  fi

  scope_len=$(jq -r '.scope | length' "$manifest" 2>/dev/null)
  if [ "$scope_len" -eq 0 ]; then
    fail "$mod_name: scope array is empty"
    continue
  fi

  scope_valid=true
  while IFS= read -r s; do
    found=false
    for vs in $VALID_SCOPES; do
      if [ "$s" = "$vs" ]; then
        found=true
        break
      fi
    done
    if [ "$found" = false ]; then
      fail "$mod_name: invalid scope value '$s' (expected one of: $VALID_SCOPES)"
      scope_valid=false
    fi
  done < <(jq -r '.scope[]' "$manifest" 2>/dev/null)

  if [ "$scope_valid" = true ]; then
    pass "$mod_name: valid scope"
  fi
done
echo ""

# --- Test: manifest-existence gate - every files map entry resolves on disk ---
# For every module.json files[] key, assert the source path exists. Uses
# [ -e ], not [ -f ], so a symlink to a file or a directory both count as
# present - only a missing path (including a broken symlink) fails. This
# guards the declared -> disk direction (a stale or mistyped manifest entry
# pointing at a deleted/renamed file). It is the companion, not the fix, for
# #930's actual bug class - three code-quality rules shipped on disk with no
# files[] entry at all - which the disk -> declared "manifest completeness"
# check below catches, but only for lib/*.sh and commands/*.md today.
echo "--- Checking manifest-existence gate (files map -> source exists) ---"
declared_entries=0
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  while IFS= read -r src_path; do
    [ -z "$src_path" ] && continue
    declared_entries=$((declared_entries + 1))
    full_path="$mod_dir/$src_path"
    if [ -e "$full_path" ]; then
      pass "$mod_name: file exists '$src_path'"
    else
      fail "$mod_name: referenced file missing '$src_path' (expected at $full_path)"
    fi
  done < <(jq -r '.files | keys[]' "$manifest" 2>/dev/null)
done
echo ""
echo "  Checked $declared_entries declared files[] entries across $module_count modules"
echo ""

# --- Test: Manifest completeness - every shipped lib/command/rule is installed ---
# Reverse of the check above: ensure no lib/*.sh, commands/*.md, or rules/*.md
# sits on disk without a files[] entry, or it silently never installs. This is
# the direction that actually catches #930's bug class (a shipped file with no
# manifest entry at all) - the forward check above only catches the opposite
# (a manifest entry pointing at a file that isn't there).
#
# Two different kinds of file types are NOT scanned here, and they are not
# the same kind of "not scanned":
#   - Genuinely never installed: README.md, terraform/, packer/, tests/.
#     These have no files[] entry by design; a scan would just be noise.
#   - Installed, but not yet covered by this gate: hooks/*.py, skills/*,
#     agents/*, bin/*. Install location is driven purely by a files[]
#     entry's `target` (type is advisory metadata only - see
#     lib/modules.sh:189-190), so an undeclared hook or skill file fails to
#     install exactly as silently as an undeclared rule did before this PR.
#     Extending the scan to those subdirs is deliberately out of scope here;
#     rules were the demonstrated gap for #930.
echo "--- Checking manifest completeness (lib + commands + rules coverage) ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  # Collect declared source paths into a newline-delimited string.
  declared=$(jq -r '.files | keys[]' "$manifest" 2>/dev/null)

  shipped_count=0
  missing_count=0
  contributed_labels=""
  for subdir in lib commands rules; do
    [ -d "$mod_dir/$subdir" ] || continue
    # Match shell scripts in lib/, markdown in commands/ and rules/. label is
    # the singular noun for the VERBOSE pass message below.
    if [ "$subdir" = "lib" ]; then
      pattern="*.sh"
      label="lib"
    elif [ "$subdir" = "commands" ]; then
      pattern="*.md"
      label="command"
    else
      pattern="*.md"
      label="rule"
    fi
    subdir_shipped=0
    # -L follows symlinks, so a shipped rule/command/lib file installed as a
    # symlink (not a plain file) is still found and checked against the
    # manifest - this is the fix for #938. A BROKEN symlink stays invisible
    # here: under -L, find only reports -type l for a link whose target does
    # not exist, so it never matches -type f. That is deliberate, not an
    # oversight - if the broken symlink IS declared, the manifest-existence
    # gate above already fails it by name (it uses [ -e ], which a broken
    # symlink fails); if it is NOT declared, it cannot install as a working
    # file either way, so there is nothing this gate would prevent by also
    # flagging it.
    while IFS= read -r abs_path; do
      [ -z "$abs_path" ] && continue
      rel_path="${abs_path#"$mod_dir"}"
      rel_path="${rel_path#/}"
      shipped_count=$((shipped_count + 1))
      subdir_shipped=$((subdir_shipped + 1))
      # Herestring, not a pipe: under `set -o pipefail`, `producer | grep -q`
      # can die with SIGPIPE if grep exits on its first match before the
      # producer finishes writing, turning a successful match into a
      # pipeline failure (see #943). A herestring has no second process to
      # race against, so there is no pipe to break.
      if grep -qxF "$rel_path" <<< "$declared"; then
        :
      else
        fail "$mod_name: shipped '$rel_path' is not in module.json files[] (will never install)"
        missing_count=$((missing_count + 1))
      fi
    done < <(find -L "$mod_dir/$subdir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null)
    if [ "$subdir_shipped" -gt 0 ]; then
      if [ -z "$contributed_labels" ]; then
        contributed_labels="$label"
      else
        contributed_labels="$contributed_labels/$label"
      fi
    fi
  done

  if [ "$shipped_count" -gt 0 ] && [ "$missing_count" -eq 0 ]; then
    pass "$mod_name: all $shipped_count shipped $contributed_labels file(s) declared in manifest"
  fi
done
echo ""

# --- Test: Manual Installation cp block -- coverage (#951) + bootstrap (#980)
#           + over-copy (#983) ---
# Both checks above compare module.json against the DISK (declared file
# exists / shipped file is declared). Neither one looks at the README's
# human-facing "Manual Installation" cp block, which is a hand-maintained
# subset of module.json's files[] and can drift independently -- #951 found
# two modules (commands-extra, brand-naming) whose Manual Installation block
# omitted files that DO install via `bash start.sh --add`, silently breaking
# the documented manual-install path.
#
# This check parses each README's Manual Installation/Install/Installation
# section for `cp` invocations (literal paths, `cp -R dir` whole-directory
# copies, `cp -R dir/*` recursive globs, `cp dir/*.ext` non-recursive globs,
# and `$VAR`/`${VAR}` shell interpolation as used in a `for` loop) and
# verifies every declared file (module.json files[] key) is covered by at
# least one of them.
#
# It checks THREE dimensions of the same block:
#
#   1. COVERAGE (#951) -- every declared file is copied by some `cp`.
#   2. DIRECTORY BOOTSTRAP (#980) -- every `cp` destination directory is
#      created by a preceding `mkdir -p` in the same section. #980 measured
#      ~40 READMEs copying into `~/.claude/commands`, `~/.claude/rules`,
#      `~/.claude/bin` and friends with no `mkdir -p`, so the documented
#      from-scratch path died on its first line with "No such file or
#      directory" for anyone who had not already run start.sh once.
#   3. OVER-COPY (#983) -- the block copies NOTHING beyond what module.json
#      declares. Coverage and over-copy are opposite directions of the same
#      containment: coverage catches an under-install, over-copy catches an
#      over-install.
#
# Bootstrap resolves a `cp`'s required destination directory statically:
# a dest ending in '/' IS the directory; a dest whose basename matches the
# source's is the copied file/dir itself, so its PARENT is the directory;
# any other single-source non-recursive copy is a renaming file copy
# (`cp settings.base.json ~/.claude/settings.json`) -- on a fresh tree the
# dest directory never pre-exists, so real cp treats dest as a file path
# and again only its PARENT must exist; anything else (multi-source or
# recursive with a differing basename) is treated as a directory target.
# A directory counts as bootstrapped by an earlier `mkdir -p X` where X is
# that directory or any descendant of it (mkdir -p creates ancestors), by
# any arg of a multi-arg `mkdir -p a b c`, or by an earlier `cp -R` that
# already created it.
#
# Bootstrap is checked by STATIC PARSING, not by executing the block into a
# scratch HOME (the approach #980 floats, and the method #970 used by hand).
# README install blocks are not hermetic and not side-effect-free: across
# the module set they `curl | tar -xz` from GitHub Releases, `git clone`,
# call `gh`, run `claude mcp add`, `bash postInstall.sh`, `npm install`,
# `source ~/.zshrc`, and `touch` opt-in flag files. Executing them in CI
# would make this suite network-dependent, slow, and capable of mutating
# the developer's real environment when a `~` slipped past the HOME
# redirect. Static parsing gives the same signal for the property actually
# under test -- "is the destination directory created first?" -- with none
# of that exposure.
#
# When a `cp` destination cannot be resolved with confidence, bootstrap
# SKIPS the line rather than guessing: `$VAR`/`${VAR}` or glob destinations
# (document-review's `for agent in ...; do cp ... "~/.claude/agents/${agent}-reviewer.md"`)
# and absolute paths outside `~` (docs-for-agents' `/path/to/your/project`
# placeholder). A false failure here would train readers to ignore this
# guard; a miss only leaves an already-existing gap unreported.
#
# Over-copy resolves each `cp`'s SOURCES against the module directory on
# disk -- literal paths as-is, glob sources via pathlib, `-R` directory
# sources by walking every file underneath -- and reports any resolved file
# that module.json's files{} does not declare. The motivating incident: #951's
# own commands-extra fix over-copied on its first attempt, sweeping 40
# undeclared files (644K, including a fixture named `evil; touch PWNED`) into
# ~/.claude via `cp -R skills/audit/*`; the guard as it then stood was
# coverage-only and stayed green throughout. It can now see that.
#
# The property is bidirectional but not total. Its honest limits:
#   - A source containing `$VAR`/`${VAR}` is NOT expanded (its value is not
#     knowable statically), so extras hiding behind an interpolated source
#     are invisible. Coverage already treats such a source as a wildcard, so
#     the two dimensions fail in opposite, safe directions there: coverage
#     over-credits it, over-copy under-reports it.
#   - A nonexistent literal source contributes nothing rather than failing;
#     "the README names a file that does not exist" is a different check
#     and deliberately not this one.
#   - Extras are computed against the FULL files{} key set, not the
#     coverage-filtered one, so `settings.partial.json` needs no special
#     case: were a block ever to `cp` it, it IS declared. (Empirically none
#     does -- confirmed by running this check across every module.)
#
# Deliberately NOT flagged, by design, not oversight:
#   - `settings.partial.json` -- a jq-merge fragment, never `cp`'d whole in
#     any of the 11 modules that declare it (verified empirically); every
#     README instead documents merging it into settings.json.
#   - `__pycache__/` directories and `*.pyc`/`*.pyo` files are dropped from
#     every source expansion. They are build droppings: start.sh never
#     installs them, and commands-extra's own block documents deleting them
#     after a recursive copy. Counting them would make over-copy fire on
#     whether someone had recently run a module's tests.
#   - GITIGNORED extras are dropped (one batched `git check-ignore --stdin`
#     per module with extras). A gitignored file can never be committed, so
#     it structurally cannot ship in a fresh clone -- a local `.DS_Store` or
#     editor swap file inside a `cp -R` source is working-copy noise, not an
#     over-copy. check-ignore never reports TRACKED files as ignored, so a
#     tracked file matching an ignore pattern is still flagged. Like
#     branch-guard's gitignore exemption, this fails CLOSED: on any git
#     error nothing is exempted and the guard stays loud.
#   - A `cp` whose destination is an ABSOLUTE path outside `~` is a
#     scaffold-into-someone-else's-project copy, not an install into the
#     CCGM tree, so its sources do not count toward the installed set.
#     One instance exists: docs-for-agents copies `templates/AGENTS.md` to
#     `/path/to/your/project/AGENTS.md`. That file is correctly undeclared
#     (start.sh does not install it; it is a template the reader copies into
#     their own repo). Bootstrap already skips this same class of line for
#     the same reason. Relative project-level destinations (`.claude/rules/`)
#     are NOT excluded -- those blocks re-copy the same declared sources the
#     `~/.claude` block does, so they add nothing to the installed set.
#   - A module whose Manual Installation section contains zero `cp`
#     invocations at all is skipped, not failed -- turning prose into a
#     false failure would make this check untrustworthy for the READMEs
#     that use it legitimately. Where the install genuinely IS "copy these
#     declared files", #983 converted the prose-only sections it found into
#     literal blocks (argus, atdd, cloud-dispatch, test-vision) and added a
#     Manual Installation section where none existed at all (deepresearch,
#     startup-dashboard). The ones that remain are skipped because their
#     install is NOT a flat copy, each for a named reason:
#       * autoheal, dreaming -- each ships 2 `__USERNAME__`-templated files
#         and requires LaunchAgent registration (autoheal additionally has a
#         settings.partial.json jq merge); the README points at
#         `start.sh --add` because a cp sequence would be a lie about what
#         installing them takes.
#       * remote-server -- `commands/onremote.md` is templated
#         (`__REMOTE_HOST__`/`__REMOTE_USER__`/`__REMOTE_ALIAS__`); copying
#         it verbatim installs a broken command, so the README documents the
#         substitution instead.
#   - A module with no Manual Installation/Install/Installation heading at
#     all has nothing to check. #983 also widened that heading match to be
#     case-insensitive and to tolerate a trailing parenthetical qualifier
#     (`## Manual installation (development clone)`), which recovered four
#     READMEs -- autoheal, dreaming, global-claude-md, plugin-marketplace --
#     that had install sections this check was simply failing to find.
# Every skip is counted and reasoned (see SKIPPED_COUNT below) so the
# "checked" number never silently implies more coverage than it has.
#
# A README that is not valid UTF-8 is reported as a FAIL naming the module,
# not an uncaught exception -- an unhandled decode error previously took
# down the rest of test-modules.sh (every check after this one silently
# never ran) instead of producing a readable failure line.
#
# KNOWN_GAPS lists modules this check found to have a real, pre-existing gap
# that is out of scope for the PR that introduced this check. A module here
# whose gap has since been fixed makes this check FAIL (stale allowlist
# entry) so the list cannot silently outlive the bugs it excuses.
#
# #951 introduced this check across six specific READMEs; three further
# gaps it also found (ccgm-doctor, documentation, session-history) were out
# of scope for that PR and tracked as #970. #970 fixed all three READMEs,
# so the list is empty again -- add an entry here only for a newly
# discovered, genuinely out-of-scope gap.
#
# OVERCOPY_KNOWN is the same construct for dimension 3, with the same
# stale-entry semantics: an allowlisted module that has no extras FAILS, so
# the allowlist cannot outlive the bug it excuses. It starts empty -- #983
# found zero real over-copies across the module set.
echo "--- Checking Manual Installation cp blocks (coverage + bootstrap + over-copy) ---"
MANUAL_INSTALL_REPORT=$(REPO_ROOT="$REPO_ROOT" python3 - <<'PYEOF'
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(os.environ["REPO_ROOT"])
MODULES = REPO_ROOT / "modules"

# Case-insensitive, and tolerant of a trailing parenthetical qualifier: four
# READMEs write `## Manual installation` or `## Manual installation
# (development clone)`, which the original case-sensitive, no-suffix pattern
# silently classed as "no install section at all" (#983). The trailing
# `\s*$` anchor is what keeps `## Installing CCGM as a marketplace` from
# matching -- only a qualifier in parentheses is accepted after the words.
HEADING_RE = re.compile(
    r'^##\s+(?:Manual\s+Installation|Installation|Install)\s*(?:\([^)\n]*\))?\s*$',
    re.MULTILINE | re.IGNORECASE,
)
ANY_HEADING_RE = re.compile(r'^##\s+', re.MULTILINE)
CP_LINE_RE = re.compile(r'cp\s+(-[A-Za-z]+\s+)?"?(?:modules/[\w.-]+/)?([\w${}/.*-]+)"?')
EXEMPT_FILENAMES = {"settings.partial.json"}

FENCE_RE = re.compile(r'^\s*```')
SHELL_SPLIT_RE = re.compile(r'&&|\|\||;|\|')
SHELL_LEAD_TOKENS = {"do", "then", "else", "sudo"}

# Build droppings: never installed by start.sh, so never an over-copy.
PYCACHE_DIR = "__pycache__"
DROPPING_SUFFIXES = (".pyc", ".pyo")

# module -> tracking issue for a known, out-of-scope pre-existing gap.
KNOWN_GAPS = {}

# Same, for dimension 3 (over-copy). Same stale-entry semantics.
OVERCOPY_KNOWN = {}

# Cap per-module OVERCOPY lines so one runaway glob cannot bury the rest of
# the suite's output; the remainder is summarized on a single line.
OVERCOPY_REPORT_CAP = 20


def shellvar_to_regex(src):
    pattern = re.escape(src)
    pattern = pattern.replace(re.escape('*'), '.*')
    pattern = re.sub(r'\\\$\\\{\w+\\\}', '.*', pattern)  # \$\{var\} -> .*
    pattern = re.sub(r'\\\$\w+', '.*', pattern)           # \$var -> .*
    return re.compile('^' + pattern + '$')


def extract_install_section(readme_text):
    m = HEADING_RE.search(readme_text)
    if not m:
        return None
    rest = readme_text[m.end():]
    m2 = ANY_HEADING_RE.search(rest)
    return rest[:m2.start()] if m2 else rest


def parse_cp_lines(section):
    out = []
    for m in CP_LINE_RE.finditer(section):
        flags = m.group(1) or ""
        out.append((bool(re.search(r'[Rr]', flags)), m.group(2)))
    return out


def shell_lines(section):
    """Yield logical shell lines from the section's fenced code blocks.

    Physical lines ending in `\\` are joined with the following line first, so
    a `cp <src> \\` / `<dest>` pair (agent-native, ce-review,
    compound-knowledge, document-review, onboarding, pr-feedback,
    session-history, ship-readiness, todos all wrap this way) parses as one
    command that has a destination, instead of two half-commands that do not.
    Restricting to fenced blocks keeps prose that merely mentions `cp` out of
    the parse.
    """
    in_fence = False
    pending = ""
    for raw in section.split("\n"):
        if FENCE_RE.match(raw):
            in_fence = not in_fence
            pending = ""
            continue
        if not in_fence:
            continue
        line = raw.rstrip()
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        yield pending + line
        pending = ""
    if pending:
        yield pending


def shell_commands(section):
    """Yield an argv token list for each shell command in the install block."""
    for line in shell_lines(section):
        text = line.strip()
        if text.startswith("#"):
            continue
        for part in SHELL_SPLIT_RE.split(text):
            part = part.strip()
            if not part:
                continue
            try:
                tokens = shlex.split(part, posix=True)
            except ValueError:
                continue  # unbalanced quotes -- not confidently parseable
            while tokens and tokens[0] in SHELL_LEAD_TOKENS:
                tokens = tokens[1:]
            if tokens:
                yield tokens


def norm_dir(path):
    stripped = path.rstrip('/')
    return stripped if stripped else '/'


def is_unresolvable(path):
    return '$' in path or '*' in path or '?' in path


def required_dest_dir(recursive, sources, dest):
    """The directory a `cp` needs to already exist. See the header comment."""
    if dest.endswith('/'):
        return norm_dir(dest)
    if len(sources) == 1 and not is_unresolvable(sources[0]):
        src = sources[0]
        # Same basename: dest names the copied file/dir itself, so only its
        # parent has to pre-exist (with -R, cp creates the last component).
        if Path(src).name == Path(dest).name:
            return norm_dir(str(Path(dest).parent))
        # Renaming file copy (`cp settings.base.json ~/.claude/settings.json`):
        # with a single non-recursive source, real cp only treats dest as a
        # directory when that directory already exists -- which on a fresh
        # tree it never does -- so dest is a file path and its parent is what
        # must pre-exist. Restricting this to matching extensions would
        # misfire on extensionless renames (`cp bin/tool ~/.claude/bin/t2`),
        # demanding a mkdir of the destination FILE. The residual trade-off
        # (a doc line intending dest as a bare directory, `cp a.md ~/x/dir`,
        # is under-required to its parent) is a mis-install cp would not
        # error on, so bootstrap cannot see it either way; 0 instances exist.
        if not recursive:
            return norm_dir(str(Path(dest).parent))
    return norm_dir(dest)


def dirs_created_by(recursive, sources, dest):
    """Directories a `cp -R` itself creates, satisfying later copies into them."""
    if not recursive:
        return []
    made = []
    for src in sources:
        if is_unresolvable(src):
            continue
        if dest.endswith('/') or Path(src).name != Path(dest).name:
            made.append(norm_dir(dest.rstrip('/') + '/' + Path(src).name))
        else:
            made.append(norm_dir(dest))
    return made


def is_bootstrapped(needed, made):
    # `mkdir -p a/b/c` creates a/b too, so a descendant entry satisfies it.
    return any(d == needed or d.startswith(needed + '/') for d in made)


def split_cp_flags_operands(tokens):
    """Split a tokenized `cp` command into (flags, operands), or None if it
    has fewer than two operands. Shared by bootstrap and over-copy so the
    two dimensions can never drift on how a `cp` line is parsed -- the same
    concern that motivated covers()'s literal-recursive branch.
    """
    flags = ''
    operands = []
    for tok in tokens[1:]:
        if tok.startswith('-') and len(tok) > 1:
            flags += tok
        else:
            operands.append(tok)
    if len(operands) < 2:
        return None
    return flags, operands


def missing_bootstrap(section):
    """Return [(directory, offending destination)] for un-mkdir'd cp targets."""
    made = []
    missing = []
    reported = set()
    for tokens in shell_commands(section):
        if tokens[0] == 'mkdir':
            for arg in tokens[1:]:
                if not arg.startswith('-'):
                    made.append(norm_dir(arg))
            continue
        if tokens[0] != 'cp':
            continue
        parsed = split_cp_flags_operands(tokens)
        if parsed is None:
            continue
        flags, operands = parsed
        recursive = bool(re.search(r'[Rr]', flags))
        sources, dest = operands[:-1], operands[-1]
        # Unresolvable or user-supplied absolute destinations are skipped,
        # never guessed at -- a false failure is worse than a miss here.
        if is_unresolvable(dest) or dest.startswith('/'):
            continue
        needed = required_dest_dir(recursive, sources, dest)
        if not is_bootstrapped(needed, made) and needed not in reported:
            reported.add(needed)
            missing.append((needed, dest))
        made.extend(dirs_created_by(recursive, sources, dest))
    return missing


def is_build_dropping(relpath):
    """__pycache__ output -- present on disk after a test run, never installed."""
    parts = Path(relpath).parts
    return PYCACHE_DIR in parts or Path(relpath).suffix in DROPPING_SUFFIXES


def strip_module_prefix(mod_name, src):
    """`modules/<name>/x` and `x` name the same file; READMEs use both forms."""
    prefix = "modules/" + mod_name + "/"
    return src[len(prefix):] if src.startswith(prefix) else src


def expand_source(mod_dir, recursive, src):
    """Module-relative files a `cp` source resolves to on disk.

    Literal file -> itself. Glob -> pathlib expansion (with -R, a matched
    directory contributes everything under it). Literal directory -> its
    whole subtree, but only with -R (without -R, cp would refuse it).
    A `$VAR` source resolves to nothing: its value is not knowable
    statically, so no extra can be attributed to it with confidence.
    A nonexistent literal source also resolves to nothing -- see the header.
    """
    if '$' in src:
        return []
    found = []
    if '*' in src or '?' in src:
        try:
            matches = sorted(mod_dir.glob(src))
        except (ValueError, OSError):
            return []
        for p in matches:
            if p.is_file():
                found.append(p)
            elif p.is_dir() and recursive:
                found.extend(q for q in sorted(p.rglob('*')) if q.is_file())
    else:
        p = mod_dir / src
        if p.is_file():
            found.append(p)
        elif p.is_dir() and recursive:
            found.extend(q for q in sorted(p.rglob('*')) if q.is_file())
    out = []
    for p in found:
        try:
            rel = str(p.relative_to(mod_dir))
        except ValueError:
            # Not lexically under the module dir (absolute source) -- skip.
            continue
        # A `../` source survives the check above (lexical prefix holds) and
        # is appended below as a reported extra: loud, the safe direction.
        # No README uses either shape today.
        if not is_build_dropping(rel):
            out.append(rel)
    return out


def installed_sources(mod_dir, section):
    """Map module-relative file -> the `cp` command that installs it.

    Keyed on SOURCE, not destination, so a README that documents both a
    `~/.claude` block and a project-level `.claude` block collapses to one
    entry per file instead of reporting each twice.
    """
    installed = {}
    for tokens in shell_commands(section):
        if tokens[0] != 'cp':
            continue
        parsed = split_cp_flags_operands(tokens)
        if parsed is None:
            continue
        flags, operands = parsed
        dest = operands[-1]
        # An absolute destination outside `~` scaffolds a file into an
        # unrelated project; it is not an install into the CCGM tree.
        if dest.startswith('/'):
            continue
        recursive = bool(re.search(r'[Rr]', flags))
        for src in operands[:-1]:
            src = strip_module_prefix(mod_dir.name, src)
            for rel in expand_source(mod_dir, recursive, src):
                installed.setdefault(rel, ' '.join(tokens))
    return installed


def drop_gitignored(mod_dir, extras):
    """Filter gitignored paths out of the over-copy extras.

    A gitignored file can never be committed, so it cannot ship in a fresh
    clone -- a local .DS_Store or editor swap file swept up by a `cp -R`
    source is working-copy noise, not a real over-copy. check-ignore never
    reports tracked files as ignored, so a tracked file that matches an
    ignore pattern is still flagged. Fails CLOSED: on any git error nothing
    is exempted and every extra stays reported.
    """
    if not extras:
        return extras
    try:
        proc = subprocess.run(
            ['git', 'check-ignore', '--stdin', '-z'],
            input='\0'.join(extras).encode() + b'\0',
            capture_output=True, cwd=mod_dir, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return extras
    if proc.returncode not in (0, 1):
        return extras
    ignored = {p.decode() for p in proc.stdout.split(b'\0') if p}
    return [e for e in extras if e not in ignored]


def covers(relpath, cp_lines):
    reldir = str(Path(relpath).parent)
    relname = Path(relpath).name
    for is_recursive, src in cp_lines:
        if '*' in src or '$' in src:
            src_dir = str(Path(src).parent)
            src_dir = '' if src_dir == '.' else src_dir
            if is_recursive:
                if src_dir == '' or reldir == src_dir or reldir.startswith(src_dir + '/'):
                    if reldir == src_dir or src_dir == '':
                        if shellvar_to_regex(Path(src).name).match(relname):
                            return True
                    else:
                        return True
            elif reldir == src_dir and shellvar_to_regex(Path(src).name).match(relname):
                return True
        elif src == relpath:
            return True
        elif is_recursive and relpath.startswith(src.rstrip('/') + '/'):
            # `cp -R skills/argus <dest>` copies the whole subtree, so every
            # file under it is covered. Without this, a literal recursive
            # directory source was invisible to coverage while over-copy
            # (which resolves sources on disk) saw straight through it --
            # the two dimensions have to agree on what a `cp` copies.
            return True
    return False


def read_text_safe(path):
    """Return (text, error) -- error is None on success. Never raises."""
    try:
        return path.read_text(), None
    except UnicodeDecodeError as e:
        return None, f"not valid UTF-8 ({e})"
    except OSError as e:
        return None, f"unreadable ({e})"


checked = 0
skipped = 0
skip_reasons = []
for mod_dir in sorted(MODULES.iterdir()):
    if not mod_dir.is_dir():
        continue
    mod_name = mod_dir.name
    manifest = mod_dir / "module.json"
    readme = mod_dir / "README.md"
    if not manifest.exists():
        skipped += 1
        skip_reasons.append((mod_name, "no module.json"))
        continue

    manifest_text, err = read_text_safe(manifest)
    if err:
        print(f"DECODE_FAIL\t{mod_name}\tmodule.json {err}")
        continue
    try:
        data = json.loads(manifest_text)
    except Exception as e:
        skipped += 1
        skip_reasons.append((mod_name, f"invalid module.json ({e})"))
        continue

    all_declared = set(data.get("files", {}))
    declared = [k for k in data.get("files", {}) if Path(k).name not in EXEMPT_FILENAMES]
    if not declared:
        skipped += 1
        skip_reasons.append((mod_name, "no declared files to check"))
        continue
    if not readme.exists():
        skipped += 1
        skip_reasons.append((mod_name, "no README.md"))
        continue

    readme_text, err = read_text_safe(readme)
    if err:
        print(f"DECODE_FAIL\t{mod_name}\tREADME.md {err}")
        continue

    section = extract_install_section(readme_text)
    if section is None:
        skipped += 1
        skip_reasons.append((mod_name, "no Manual Installation/Install/Installation heading"))
        continue
    cp_lines = parse_cp_lines(section)
    if not cp_lines:
        skipped += 1
        skip_reasons.append((mod_name, "no parseable cp invocation (prose-only or whole-dir instructions)"))
        continue

    checked += 1
    missing = [r for r in declared if not covers(r, cp_lines)]
    if mod_name in KNOWN_GAPS:
        if not missing:
            print(f"STALE\t{mod_name}\tallowlisted for {KNOWN_GAPS[mod_name]} but has no missing files now -- remove from KNOWN_GAPS")
        # else: known, tracked, intentionally silent.
    else:
        for relpath in missing:
            print(f"MISSING\t{mod_name}\t{relpath}")

    # Dimension 2 (#980): destination directories must be created first.
    # KNOWN_GAPS allowlists file-coverage gaps only, so it does not apply.
    for needed, dest in missing_bootstrap(section):
        print(f"NOMKDIR\t{mod_name}\t'{needed}' (copy destination: {dest})")

    # Dimension 3 (#983): the block must copy nothing beyond files{}.
    installed = installed_sources(mod_dir, section)
    extras = drop_gitignored(mod_dir, sorted(set(installed) - all_declared))
    if mod_name in OVERCOPY_KNOWN:
        if not extras:
            print(f"STALE\t{mod_name}\tallowlisted for {OVERCOPY_KNOWN[mod_name]} but copies nothing undeclared now -- remove from OVERCOPY_KNOWN")
        # else: known, tracked, intentionally silent.
    else:
        for relpath in extras[:OVERCOPY_REPORT_CAP]:
            print(f"OVERCOPY\t{mod_name}\t{relpath}\t{installed[relpath]}")
        if len(extras) > OVERCOPY_REPORT_CAP:
            rest = len(extras) - OVERCOPY_REPORT_CAP
            print(f"OVERCOPY\t{mod_name}\t(and {rest} more undeclared file(s))\t-")

print(f"CHECKED\t{checked}")
print(f"SKIPPED_COUNT\t{skipped}")
for mod_name, reason in skip_reasons:
    print(f"SKIPPED_DETAIL\t{mod_name}\t{reason}")
PYEOF
)

while IFS=$'\t' read -r kind mod_name detail source_cmd; do
  [ -z "$kind" ] && continue
  case "$kind" in
    MISSING)
      fail "$mod_name: Manual Installation cp block never installs '$detail' (declared in module.json but no cp/glob covers it)"
      ;;
    NOMKDIR)
      fail "$mod_name: Manual Installation block copies into $detail with no preceding 'mkdir -p' -- the documented steps fail against a fresh ~/.claude"
      ;;
    OVERCOPY)
      if [ "$source_cmd" = "-" ]; then
        # The per-module cap's summary line ("(and N more undeclared
        # file(s))") is not a file path; render it bare.
        fail "$mod_name: $detail"
      else
        fail "$mod_name: Manual Installation block installs '$detail', which module.json does not declare (swept in by: $source_cmd)"
      fi
      ;;
    STALE)
      fail "$mod_name: $detail"
      ;;
    DECODE_FAIL)
      fail "$mod_name: $detail -- cannot check Manual Installation coverage"
      ;;
  esac
done < <(printf '%s\n' "$MANUAL_INSTALL_REPORT" | grep -E '^(MISSING|NOMKDIR|OVERCOPY|STALE|DECODE_FAIL)')

checked_count=$(printf '%s\n' "$MANUAL_INSTALL_REPORT" | grep '^CHECKED' | cut -f2)
skipped_count=$(printf '%s\n' "$MANUAL_INSTALL_REPORT" | grep '^SKIPPED_COUNT' | cut -f2)
# Unconditional, like the "Checked N declared files[] entries..." line above
# -- a guard's coverage must never be invisible in default (non-VERBOSE)
# output, or its silence gets mistaken for completeness.
echo "  Checked $checked_count module(s), skipped ${skipped_count:-0} (no install section or no parseable cp command)"
if [ -n "$checked_count" ] && [ "$checked_count" -gt 0 ]; then
  pass "Manual Installation cp-block coverage + directory bootstrap + over-copy checked across $checked_count module(s)"
fi
if [ "$VERBOSE" = "1" ] && [ -n "$skipped_count" ] && [ "$skipped_count" -gt 0 ]; then
  echo "  Skipped modules:"
  printf '%s\n' "$MANUAL_INSTALL_REPORT" | grep '^SKIPPED_DETAIL' | while IFS=$'\t' read -r _ mod_name reason; do
    echo "    - $mod_name: $reason"
  done
fi
echo ""

# --- Test: Dependencies reference real modules ---
echo "--- Checking dependencies ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  dep_count=$(jq -r '.dependencies | length' "$manifest" 2>/dev/null)
  if [ "$dep_count" -eq 0 ]; then
    pass "$mod_name: no dependencies (ok)"
    continue
  fi

  while IFS= read -r dep; do
    if [ -d "$REPO_ROOT/modules/$dep" ] && [ -f "$REPO_ROOT/modules/$dep/module.json" ]; then
      pass "$mod_name: dependency '$dep' exists"
    else
      fail "$mod_name: dependency '$dep' does not exist"
    fi
  done < <(jq -r '.dependencies[]' "$manifest" 2>/dev/null)
done
echo ""

# --- Test: Presets reference real modules ---
echo "--- Checking presets ---"
for preset_file in "$REPO_ROOT"/presets/*.json; do
  [ ! -f "$preset_file" ] && continue
  preset_name=$(basename "$preset_file" .json)

  if ! jq empty "$preset_file" 2>/dev/null; then
    fail "preset '$preset_name': invalid JSON"
    continue
  fi

  pass "preset '$preset_name': valid JSON"

  while IFS= read -r mod; do
    if [ -d "$REPO_ROOT/modules/$mod" ]; then
      pass "preset '$preset_name': module '$mod' exists"
    else
      fail "preset '$preset_name': references non-existent module '$mod'"
    fi
  done < <(jq -r '.[]' "$preset_file" 2>/dev/null)
done
echo ""

# --- Test: every tests/test-*.sh suite is wired into CI, in every job ---
# tests/run-all.sh discovers suites by globbing "$SCRIPT_DIR"/test-*.sh, but
# .github/workflows/test.yml enumerates each suite by hand as its own step,
# once per job. The two lists drift silently (issue #935): a suite can exist
# on disk, run green under run-all.sh, and never once gate a PR because no
# one added its step to the workflow -- or added it to one job and not the
# other, which is the same bug in miniature.
echo "--- Checking CI enumeration coverage (test.yml) ---"
WORKFLOW_FILE="$REPO_ROOT/.github/workflows/test.yml"
if [ ! -f "$WORKFLOW_FILE" ]; then
  fail "workflow file missing: .github/workflows/test.yml"
else
  # No pipe: `grep -n ... | head -1 | cut -d: -f1` races `head -1` closing
  # its read end against `grep` still writing (same SIGPIPE hazard as #943).
  # `-m1` makes grep itself stop after the first match instead, and the
  # `:1` field split is plain bash parameter expansion - no second process
  # is ever reading from another live process's stdout.
  jobs_match=$(grep -m1 -n '^jobs:[[:space:]]*$' "$WORKFLOW_FILE" || true)
  jobs_line="${jobs_match%%:*}"
  if [ -z "$jobs_line" ]; then
    fail "test.yml: could not locate top-level 'jobs:' key"
  else
    total_lines=$(wc -l < "$WORKFLOW_FILE" | tr -d ' ')

    # Job boundaries: lines shaped like "  <job-name>:" (exactly 2-space
    # indent, colon, then only whitespace and/or a trailing "# comment")
    # that appear after the top-level "jobs:" key. Each one starts a new
    # job; the next one (or EOF) ends it. This scopes the check to per-job
    # step lists rather than treating the file as one flat blob, so a suite
    # wired into ubuntu but not macos is caught -- not silently passed by a
    # whole-file grep. The trailing-comment tolerance matters: without it,
    # a routine "test-macos: # runs on macOS" edit drops a job boundary and
    # merges two jobs' ranges into one, silently disabling the per-job
    # check it is supposed to run (see the job-count assertion below).
    ranges=""
    job_names=""
    prev=""
    while IFS= read -r ln; do
      if [ -n "$prev" ]; then
        end=$((ln - 1))
        ranges="${ranges}${prev}:${end}
"
      fi
      prev="$ln"
    done < <(tail -n "+$((jobs_line + 1))" "$WORKFLOW_FILE" | grep -nE '^  [A-Za-z0-9_-]+:[[:space:]]*(#.*)?$' | cut -d: -f1 | while IFS= read -r n; do echo $((n + jobs_line)); done)
    if [ -n "$prev" ]; then
      ranges="${ranges}${prev}:${total_lines}
"
    fi

    while IFS= read -r range; do
      [ -z "$range" ] && continue
      start="${range%%:*}"
      name=$(sed -n "${start}p" "$WORKFLOW_FILE" | sed 's/^[[:space:]]*//; s/:.*$//')
      job_names="$job_names $name"
    done < <(printf '%s' "$ranges")

    job_count=$(printf '%s\n' "$ranges" | grep -c ':' || true)
    # Load-bearing check: assert a floor, not just "> 0". A job-boundary
    # parsing regression (trailing comment, changed indent, a run: block
    # that happens to contain a job-key-shaped line, ...) degrades the
    # per-job scoping silently -- every suite present anywhere in the file
    # then satisfies a single merged range and the guard reports all-green,
    # exactly the whole-file-grep weakness this check exists to prevent.
    # Failing loud here, naming what was actually detected, converts that
    # class of regression into a red test instead of manufactured
    # confidence. Raise MIN_EXPECTED_CI_JOBS if a legitimate third job is
    # ever added; do not hardcode an exact-equals that would break on that.
    MIN_EXPECTED_CI_JOBS=2
    if [ "$job_count" -lt "$MIN_EXPECTED_CI_JOBS" ]; then
      fail "test.yml: expected >= $MIN_EXPECTED_CI_JOBS CI job(s) under 'jobs:', found $job_count (detected:${job_names:- none}) -- job-boundary parsing may be broken (e.g. a trailing comment or unexpected indent on a job key line)"
    else
      pass "test.yml: found $job_count job definition(s) under 'jobs:' (${job_names# })"

      for suite_path in "$SCRIPT_DIR"/test-*.sh; do
        [ -f "$suite_path" ] || continue
        suite_name=$(basename "$suite_path")
        missing_in=""

        while IFS= read -r range; do
          [ -z "$range" ] && continue
          start="${range%%:*}"
          end="${range##*:}"
          job_label=$(sed -n "${start}p" "$WORKFLOW_FILE" | sed 's/^[[:space:]]*//; s/:.*$//')
          # Capture the job's slice first, then match against the variable
          # with a herestring instead of piping sed straight into
          # `grep -qF`. Same SIGPIPE hazard as #943: `grep -q` can exit on
          # its first match before `sed` finishes writing the range, and
          # under pipefail that turns a real match into a false "missing"
          # report - here, for every job after the first suite line found.
          job_slice=$(sed -n "${start},${end}p" "$WORKFLOW_FILE")
          if grep -qF "tests/$suite_name" <<< "$job_slice"; then
            :
          else
            missing_in="$missing_in $job_label"
          fi
        done < <(printf '%s' "$ranges")

        if [ -z "$missing_in" ]; then
          pass "$suite_name: wired into all $job_count CI job(s)"
        else
          fail "$suite_name: missing from CI job(s):$missing_in (add 'run: bash tests/$suite_name' to .github/workflows/test.yml)"
        fi
      done
    fi
  fi
fi
echo ""

# --- Summary ---
echo "==================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==================================="

if [ $FAIL -gt 0 ]; then
  echo ""
  echo "Failures:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  exit 1
fi

exit 0
