#!/usr/bin/env bash
set -uo pipefail

# CCGM Cross-Module Invocation Guard (GitHub issue #926)
#
# A module's shipped executables may invoke a script that ANOTHER module
# installs (`python3 ~/.claude/lib/agent_tracking.py`, `bash
# ~/.claude/lib/worktree-sweep.sh`, ...). Whenever they do, exactly one of two
# things must be true, or the caller breaks on a selective install
# (`start.sh --add <module>`, or any preset that omits the owner):
#
#   (a) the caller DECLARES a dependency on the owning module, so the file is
#       always installed alongside it; or
#   (b) the call is GUARDED, so a missing file degrades instead of erroring.
#
# Both are legitimate; which one is right depends on whether the feature is
# core or supplementary. Option (b) is sometimes the ONLY correct answer: on
# 2026-07-30 startup-dashboard invoked multi-agent's handoff.py, and since
# multi-agent already depends on startup-dashboard, declaring the reverse
# would have been a dependency cycle. The guard is the design there.
#
# HONEST SCOPE: this finds zero violations at the time it was written — all
# three existing cross-module invocations are already guarded. It is a
# regression guard that pins the property, not a bug finder. It does NOT
# police prose: a rule that merely mentions another module's hook by name is
# not an invocation. (That class is why multi-agent needed a `hooks`
# dependency, and no mechanical check can settle it — see #926.)
#
# Run: bash tests/test-cross-module-invocations.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 is required for tests/test-cross-module-invocations.sh" >&2
  exit 1
fi

# Python does the walking: BSD/GNU grep differences and the guard detection
# are both fiddly in portable shell, and this is deterministic parsing work.
python3 - "$@" <<'PY'
import glob
import json
import os
import re
import sys

SELF_TEST = "--self-test" in sys.argv

mods = {}
owner = {}          # installed basename -> owning module name
for f in glob.glob("modules/*/module.json"):
    m = json.load(open(f))
    mods[m["name"]] = m
    for src, spec in m["files"].items():
        target = spec.get("target", src) if isinstance(spec, dict) else src
        owner[os.path.basename(target)] = m["name"]


def closure(name, seen=None):
    """Full dependency closure of a module, cycle-safe."""
    seen = seen if seen is not None else set()
    if name in seen:
        return seen
    seen.add(name)
    for dep in mods[name]["dependencies"]:
        if dep in mods:
            closure(dep, seen)
    return seen


# An invocation is an interpreter (or a bare path) followed by an installed
# CCGM path. A mention inside prose does not match, because prose does not put
# `python3`/`bash`/`sh` immediately in front of the path.
INVOKE = re.compile(
    r"(?:python3?|bash|sh|zsh|source|\.)\s+"
    r"[\"']?~/\.claude/(?:hooks|lib|bin)/([A-Za-z0-9_.-]+\.(?:py|sh))"
)

# A call is guarded when a missing file cannot fail the caller: `|| true`,
# `|| echo ...`, `2>/dev/null ||`, or an explicit existence test.
GUARD = re.compile(r"\|\|\s*(?:true|:|echo\b)|2>\s*/dev/null\s*\|\||\[\s*-[fex]\s")


def is_executable_source(path):
    """Only a module's own runnable files can invoke anything at runtime."""
    return path.endswith((".sh", ".py"))


def logical_lines(path):
    """Yield (first_lineno, joined_text) with backslash continuations merged.

    A shell call is routinely split across lines, with the guard on the
    continuation:

        python3 ~/.claude/lib/handoff.py summary \\
          --repo "$REPO" 2>/dev/null || true

    Matching line-at-a-time would see the invocation without its guard and
    report a false violation.
    """
    buf, start = "", None
    for lineno, raw in enumerate(open(path, errors="ignore"), 1):
        line = raw.rstrip("\n")
        if start is None:
            start = lineno
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        yield start, buf + line
        buf, start = "", None
    if start is not None:
        yield start, buf


def inside_string_literal(text, pos):
    """True if offset `pos` sits inside a quoted string.

    Advisory text embedded in a message is not an invocation. The hook that
    blocks `git branch -D` prints `bash ~/.claude/lib/worktree-sweep.sh ...`
    as a suggestion for the human to run; the hook itself never executes it,
    so it must not be read as a dependency.
    """
    head = text[:pos]
    return (head.count('"') - head.count('\\"')) % 2 == 1 or \
           (head.count("'") - head.count("\\'")) % 2 == 1


def scan():
    """Yield (caller, script, owner, guarded, location) per invocation."""
    for name, m in mods.items():
        own_targets = {
            os.path.basename(s.get("target", src) if isinstance(s, dict) else src)
            for src, s in m["files"].items()
        }
        for path in sorted(glob.glob(f"modules/{name}/**/*", recursive=True)):
            if not os.path.isfile(path) or not is_executable_source(path):
                continue
            for lineno, line in logical_lines(path):
                for m in INVOKE.finditer(line):
                    script = m.group(1)
                    o = owner.get(script)
                    if o is None or o == name or script in own_targets:
                        continue
                    if inside_string_literal(line, m.start()):
                        continue
                    yield (
                        name, script, o,
                        bool(GUARD.search(line)),
                        f"{path}:{lineno}",
                    )


if SELF_TEST:
    # The detector must distinguish an invocation from a mention, and a
    # guarded call from a bare one. Without this, "0 violations" is
    # indistinguishable from a regex that never matches anything.
    cases = [
        ('python3 ~/.claude/lib/agent_tracking.py list', True, False, "bare invocation"),
        ('python3 ~/.claude/lib/agent_tracking.py list 2>/dev/null || true', True, True, "guarded with || true"),
        ('python3 ~/.claude/lib/x.py 2>/dev/null || echo "unavailable"', True, True, "guarded with || echo"),
        ('bash ~/.claude/lib/worktree-sweep.sh --merged-branches', True, False, "bash invocation"),
        ('A PreToolUse hook (`~/.claude/hooks/port-check.py`) warns about ports', False, False, "prose mention"),
        ('see ~/.claude/lib/hook_utils.py for details', False, False, "comment reference"),
        # Continuation: the guard lands on the second physical line. Matching
        # line-at-a-time would call this an unguarded invocation.
        ('python3 ~/.claude/lib/handoff.py summary   --repo "$R" 2>/dev/null || true',
         True, True, "guard on a continued line"),
    ]
    failures = 0
    for line, want_invoke, want_guard, label in cases:
        got_invoke = bool(INVOKE.search(line))
        if got_invoke != want_invoke:
            print(f"  FAIL: self-test invocation detection ({label}): "
                  f"expected {want_invoke}, got {got_invoke}")
            failures += 1
            continue
        if want_invoke:
            got_guard = bool(GUARD.search(line))
            if got_guard != want_guard:
                print(f"  FAIL: self-test guard detection ({label}): "
                      f"expected {want_guard}, got {got_guard}")
                failures += 1

    # Continuation joining must actually merge the physical lines.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write('python3 ~/.claude/lib/handoff.py summary \\\n'
                 '  --repo "$R" 2>/dev/null || true\n')
        tmp = fh.name
    joined = [t for _, t in logical_lines(tmp)]
    os.unlink(tmp)
    if not any("handoff.py" in t and "|| true" in t for t in joined):
        print("  FAIL: self-test — backslash continuation was not joined")
        failures += 1

    # A quoted suggestion is advisory text, not an invocation.
    advisory = '            "  bash ~/.claude/lib/worktree-sweep.sh --worktree <path>\\n"'
    m = INVOKE.search(advisory)
    if not m or not inside_string_literal(advisory, m.start()):
        print("  FAIL: self-test — quoted advisory text not recognized as a string literal")
        failures += 1

    if failures:
        print(f"test-cross-module-invocations.sh --self-test: {failures} failed")
        sys.exit(1)
    print(f"ok: self-test — {len(cases)} detector cases, continuation joining, "
          f"and string-literal exclusion")
    print("test-cross-module-invocations.sh --self-test: all checks passed")
    sys.exit(0)

violations = []
guarded = []
for caller, script, o, is_guarded, where in scan():
    if o in closure(caller) or is_guarded:
        guarded.append((caller, script, o, is_guarded, where))
    else:
        violations.append((caller, script, o, where))

for caller, script, o, is_guarded, where in guarded:
    how = "declares dependency" if o in closure(caller) else "guarded call"
    print(f"ok: {caller} -> {script} (owned by {o}): {how}  [{where}]")

for caller, script, o, where in violations:
    print(f"FAIL: {caller} invokes {script}, owned by '{o}', with neither a "
          f"declared dependency nor a guard: {where}", file=sys.stderr)
    print(f"      Fix by adding '{o}' to {caller}'s dependencies, or by "
          f"guarding the call (`2>/dev/null || true`) if the feature is "
          f"supplementary.", file=sys.stderr)

total = len(guarded) + len(violations)
print(f"\ntest-cross-module-invocations.sh: {total} cross-module invocation(s), "
      f"{len(violations)} unprotected")
sys.exit(1 if violations else 0)
PY
