"""Rule-tiering support library (plan.md `~/code/plans/ccgm-dynamic-rule-injection/plan.md`,
Epic 1 -- issue #954).

THIS FILE IS INTENTIONALLY INCOMPLETE. Epic 1's scope is the `paths:`
version floor only -- Epic 4 owns the real generator (`validate()`,
`render_frontmatter()` proper, `render_index()`, `strip_frontmatter()`;
idempotent, atomic, path-confined, byte-reversible). Do not extend this
module beyond what is documented below without reading Epic 4's spec
first; a signature added here casually is a signature Epic 4 either has
to keep or has to break.

What lives here today
----------------------
  claude_code_supports_paths(version_string=None) -> bool
      The version-floor check. `paths:` frontmatter on rule files shipped
      broken in several point releases before it stabilized (plan.md
      §1.2 insight 1 cites 2.1.198, 2.1.207, 2.1.211, 2.1.217 as the fix
      train; research-e-orchestrator-firsthand.md's decisive experiment
      ran on 2.1.220). MIN_SUPPORTED_VERSION is pinned to 2.1.207, the
      first release in that train the plan treats as stable.

  render_frontmatter(target_path, paths, *, version_string=None) -> (bool, str)
      A MINIMAL, gated write path -- NOT the Epic 4 generator. It exists
      solely so Epic 1's test_version_floor_gates_writes.py has a real
      write path to prove the version floor actually gates (the security
      review's finding: a floor that is unit-tested in isolation but
      never proven to gate the write path is not a floor). It has NONE
      of the properties the real generator will need: it is not
      idempotent, not atomic, not byte-reversible, and does not validate
      that `target_path` is confined to a module directory. Epic 4 owns
      building that generator from scratch; this function's only
      contract is "does nothing when the version floor is not met".
"""
from __future__ import annotations

import os
import re
import subprocess

# First Claude Code release this plan treats as a stable `paths:`
# implementation. Below this, the frontmatter is either ignored (rule
# loads unconditionally, defeating Tier B silently) or -- per plan.md
# R6 -- one invalid pattern below 2.1.207 breaks the Read tool for
# EVERY evaluated file. Either failure mode is worse than not writing
# the frontmatter at all, hence the fail-safe (False) default below.
MIN_SUPPORTED_VERSION = (2, 1, 207)

_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse_version(version_string: str) -> "tuple[int, int, int] | None":
    """Parse the first X.Y.Z triple out of a version string.

    Accepts both a bare version ("2.1.220") and the real `claude
    --version` shape ("2.1.220 (Claude Code)") by searching for the
    pattern anywhere in the string rather than anchoring to its start.

    Returns None if no such triple is found -- the caller (
    claude_code_supports_paths) treats this as fail-safe False, never
    as "assume supported".
    """
    if not isinstance(version_string, str):
        return None
    match = _VERSION_PATTERN.search(version_string)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def claude_code_supports_paths(version_string: "str | None" = None) -> bool:
    """True iff the given (or running) Claude Code version supports
    `paths:` frontmatter on rule files.

    version_string:
        - If provided, parsed directly (no subprocess call). This is
          the path every unit test exercises, so the check is fully
          deterministic in CI with no `claude` CLI required.
        - If None (the default), shells out to `claude --version` and
          parses its stdout. Any failure to invoke `claude` at all
          (not installed, not on PATH, times out) is caught and treated
          as fail-safe False -- never as "assume supported".

    Fail-safe on every unparseable or unobtainable input: returns False,
    never True, when the version cannot be determined. A caller that
    cannot prove the version supports `paths:` must not write it.
    """
    if version_string is None:
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        version_string = (result.stdout or "") + (result.stderr or "")

    parsed = _parse_version(version_string)
    if parsed is None:
        return False
    return parsed >= MIN_SUPPORTED_VERSION


def render_frontmatter(
    target_path: str,
    paths: "list[str]",
    *,
    version_string: "str | None" = None,
) -> "tuple[bool, str]":
    """Minimal, version-gated write path. NOT the Epic 4 generator -- see
    the module docstring before extending this.

    Returns (wrote, reason):
      - (False, reason) and `target_path` is left completely untouched
        (not created, not modified) when `claude_code_supports_paths()`
        is False for the given/running version. This is the behavior
        test_version_floor_gates_writes.py asserts.
      - (True, reason) and a block-sequence `paths:` frontmatter block
        is prepended to `target_path`'s existing content (or written
        alone if `target_path` does not yet exist), when the version
        check passes.

    `paths` must be a non-empty list of glob strings; each is emitted as
    its own quoted block-sequence entry (never flow-style `[...]`) per
    plan.md §8.3's "Emitted YAML" requirement -- flow-style is rejected
    by the repo's frontmatter-YAML guard.
    """
    if not claude_code_supports_paths(version_string):
        return False, (
            "claude_code_supports_paths() is False -- refusing to write "
            f"paths: frontmatter to {target_path!r}"
        )

    if not paths:
        return False, "refusing to write paths: frontmatter with an empty paths list"

    frontmatter_lines = ["---", "paths:"]
    frontmatter_lines.extend(f'  - "{glob}"' for glob in paths)
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines) + "\n"

    existing_body = ""
    if os.path.isfile(target_path):
        with open(target_path, "r", encoding="utf-8") as fh:
            existing_body = fh.read()

    with open(target_path, "w", encoding="utf-8") as fh:
        fh.write(frontmatter + existing_body)

    return True, f"wrote paths: frontmatter to {target_path!r}"
