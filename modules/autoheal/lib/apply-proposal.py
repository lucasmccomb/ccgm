"""
Shared proposal-apply implementation for /permission-fix and /autoheal-apply.

Both commands route through `apply_proposal()` so the branch shape, the
commit message format, the test gate, and the audit record are exactly
the same. Diverging the apply path between manual and auto invocation
would mean two slightly different ways for proposals to land on main,
which defeats the audit trail.

Locked behavior (Section 3.9 of plan.md):

  1. Find proposal by id in ~/.claude/autoheal/proposals/{today}.jsonl
  2. Resolve canonical CCGM clone path (walk up looking for start.sh,
     fall back to ~/code/ccgm/)
  3. Verify clean working tree on main; commit any WIP per CCGM
     no-stash rule before continuing.
  4. Create branch autoheal/{id} (source="permission-fix") or
     autoheal/auto/{id} (source="auto-apply").
  5. Apply diff via `git apply` against `proposed_diff_target`.
  6. Run tests/test-modules.sh + tests/test-no-personal-data.sh.
  7. On pass: commit with message `#auto: apply autoheal proposal {id}`.
  8. Append a record to ~/.claude/autoheal/applied/{today}.jsonl.
  9. Print `git diff HEAD~1` + the literal "To undo: git revert HEAD".
 10. Print a suggested `gh pr create` command. Never auto-merge.

The function returns a dict so the caller can present the result
without re-parsing prose. Stdout is reserved for human-facing output
(diff, undo hint, PR-create suggestion); stderr for warnings; the
return value is the machine-readable success/failure summary.

Env overrides (tests):
  - CCGM_AUTOHEAL_PROPOSALS_DIR — default ~/.claude/autoheal/proposals
  - CCGM_AUTOHEAL_APPLIED_DIR   — default ~/.claude/autoheal/applied
  - CCGM_AUTOHEAL_TODAY         — YYYY-MM-DD override
  - CCGM_CLONE_ROOT             — explicit clone root (skips resolve)
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys

# Source labels for apply_proposal. The string is used as part of the
# branch name and as the `method` value in the applied audit record.
SOURCE_PERMISSION_FIX = "permission-fix"
SOURCE_AUTO_APPLY = "auto-apply"


def _today_str() -> str:
    override = os.environ.get("CCGM_AUTOHEAL_TODAY")
    if override:
        return override
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _proposals_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_PROPOSALS_DIR") or os.path.expanduser(
        "~/.claude/autoheal/proposals"
    )


def _applied_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_APPLIED_DIR") or os.path.expanduser(
        "~/.claude/autoheal/applied"
    )


def _find_proposal(proposal_id: str) -> dict | None:
    """Walk today's proposals JSONL for the requested id; return None if absent.

    JSONL scan is intentionally linear: proposal volume is bounded
    (tens per day) so an index file is not worth the complexity.
    """
    path = os.path.join(_proposals_dir(), _today_str() + ".jsonl")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(rec, dict) and rec.get("id") == proposal_id:
                    return rec
    except OSError:
        return None
    return None


def _resolve_clone_root(start_cwd: str | None = None) -> str | None:
    """
    Resolve the canonical CCGM clone path.

    Search order:
      1. CCGM_CLONE_ROOT env var (tests + explicit override).
      2. Walk up from `start_cwd` (default os.getcwd()) until a
         directory containing `start.sh` is found.
      3. Fall back to ~/code/ccgm/ if it exists.

    Returns None if no candidate satisfies the search.
    """
    explicit = os.environ.get("CCGM_CLONE_ROOT")
    if explicit and os.path.isfile(os.path.join(explicit, "start.sh")):
        return explicit

    here = os.path.abspath(start_cwd or os.getcwd())
    seen: set[str] = set()
    while here and here not in seen:
        seen.add(here)
        if os.path.isfile(os.path.join(here, "start.sh")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent

    fallback = os.path.expanduser("~/code/ccgm")
    if os.path.isfile(os.path.join(fallback, "start.sh")):
        return fallback
    return None


def _run(
    cmd: list[str], cwd: str, env: dict | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run with consistent capture/text behavior."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=env if env is not None else os.environ.copy(),
    )


def _git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git"] + args, cwd=cwd, check=check)


def _ensure_clean_main(cwd: str) -> tuple[bool, str]:
    """
    Verify the working tree is clean on main. If there is uncommitted
    work, commit it as a WIP per the CCGM no-stash rule rather than
    losing it.

    Returns (ok, message).
    """
    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()
    except subprocess.CalledProcessError as exc:
        return False, f"git rev-parse failed: {exc.stderr.strip()}"

    if branch != "main":
        # Apply may still proceed but is safer from main. We do not
        # auto-checkout main: the user might have intentional WIP on
        # a feature branch. Surface and bail.
        return False, f"not on main (current: {branch}); checkout main first"

    status = _git(["status", "--porcelain"], cwd).stdout
    if status.strip():
        # Commit WIP so subsequent apply is on a known-good base.
        try:
            _git(["add", "-A"], cwd)
            env = os.environ.copy()
            env["ALLOW_MAIN_COMMIT"] = "1"
            _run(
                ["git", "commit", "-m", "#auto: WIP before autoheal apply"],
                cwd,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            return False, f"WIP commit failed: {exc.stderr.strip()}"

    return True, ""


def _branch_name(proposal_id: str, source: str) -> str:
    if source == SOURCE_AUTO_APPLY:
        return f"autoheal/auto/{proposal_id}"
    return f"autoheal/{proposal_id}"


def _create_branch(cwd: str, branch: str) -> tuple[bool, str]:
    """Create and check out the branch; refuse if it already exists."""
    existing = _git(
        ["branch", "--list", branch], cwd, check=False
    ).stdout.strip()
    if existing:
        return False, f"branch {branch} already exists"
    try:
        _git(["checkout", "-b", branch], cwd)
    except subprocess.CalledProcessError as exc:
        return False, f"checkout -b failed: {exc.stderr.strip()}"
    return True, ""


def _apply_diff(cwd: str, diff_text: str, target: str) -> tuple[bool, str]:
    """
    Apply the unified diff text via `git apply`.

    We feed the diff over stdin instead of writing it to a tempfile.
    `git apply --check` first so we fail loudly if the diff would not
    apply cleanly.
    """
    if not diff_text or not target:
        return False, "empty diff or target"
    if not target.startswith("modules/"):
        return False, f"diff target must be under modules/: {target}"

    try:
        check = subprocess.run(
            ["git", "apply", "--check"],
            cwd=cwd,
            input=diff_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:
            return False, f"git apply --check failed: {check.stderr.strip()}"

        apply = subprocess.run(
            ["git", "apply"],
            cwd=cwd,
            input=diff_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if apply.returncode != 0:
            return False, f"git apply failed: {apply.stderr.strip()}"
    except OSError as exc:
        return False, f"git apply: {exc}"

    return True, ""


def _run_tests(cwd: str) -> tuple[bool, str]:
    """Run the two pre-commit guardrails. Both must pass."""
    for script in ("tests/test-modules.sh", "tests/test-no-personal-data.sh"):
        path = os.path.join(cwd, script)
        if not os.path.isfile(path):
            return False, f"missing test script: {script}"
        proc = _run(["bash", script], cwd=cwd, check=False)
        if proc.returncode != 0:
            tail = (proc.stdout or "") + "\n" + (proc.stderr or "")
            return False, f"{script} failed:\n{tail[-2000:]}"
    return True, ""


def _commit(cwd: str, proposal_id: str) -> tuple[bool, str]:
    """
    Commit the staged diff. We stage with `git add -A` because the
    proposal's `proposed_diff_target` could span multiple files under
    `modules/`. ALLOW_MAIN_COMMIT is not needed (we are on the new
    branch, not main).
    """
    try:
        _git(["add", "-A"], cwd)
        msg = f"#auto: apply autoheal proposal {proposal_id}"
        _git(["commit", "-m", msg], cwd)
        sha = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    except subprocess.CalledProcessError as exc:
        return False, f"commit failed: {exc.stderr.strip()}"
    return True, sha


def _print_diff(cwd: str) -> None:
    """Print `git diff HEAD~1` to stdout for human review."""
    proc = _run(["git", "diff", "HEAD~1"], cwd=cwd, check=False)
    if proc.stdout:
        sys.stdout.write(proc.stdout)
        sys.stdout.flush()


def _print_followup(branch: str, proposal_id: str) -> None:
    """Print the undo hint and a suggested PR-create command."""
    sys.stdout.write("\nTo undo: git revert HEAD\n")
    sys.stdout.write(
        f'\nSuggested PR command:\n'
        f'  git push -u origin {branch}\n'
        f'  gh pr create --title "autoheal: apply proposal {proposal_id}" '
        f'--body "Applied autoheal proposal {proposal_id} via apply-proposal.py. '
        f'Tests gated. Review the diff before merging."\n'
    )
    sys.stdout.flush()


def _append_applied_record(record: dict) -> None:
    """
    Append a JSONL record to the applied audit file. We use
    hook_utils.file_locked_append if available so cross-clone writers
    cannot truncate each other; fall back to direct append if the
    helper cannot be imported (e.g., during local unit tests without
    the hooks module installed).
    """
    path = os.path.join(_applied_dir(), _today_str() + ".jsonl")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = json.dumps(record, separators=(",", ":")) + "\n"
    try:
        sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
        import hook_utils  # type: ignore

        hook_utils.file_locked_append(path, payload)
        return
    except ImportError:
        pass
    # Fallback: plain append. Risk of interleaving exists only when
    # multiple apply runs race, which is rare in practice.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(payload)


def apply_proposal(proposal_id: str, source: str = SOURCE_PERMISSION_FIX) -> dict:
    """
    Apply a proposal to the canonical CCGM clone source.

    Args:
        proposal_id: id of the proposal in today's proposals.jsonl.
        source: "permission-fix" or "auto-apply". Determines branch
                shape and the `method` field in the audit record.

    Returns:
        {
            "success": bool,
            "branch": str | None,
            "commit_sha": str | None,
            "error": str | None,
            "proposal_id": str,
        }
    """
    result: dict = {
        "success": False,
        "branch": None,
        "commit_sha": None,
        "error": None,
        "proposal_id": proposal_id,
    }

    proposal = _find_proposal(proposal_id)
    if proposal is None:
        result["error"] = f"proposal {proposal_id} not found in today's JSONL"
        return result

    cwd = _resolve_clone_root()
    if cwd is None:
        result["error"] = "could not resolve canonical CCGM clone root"
        return result

    ok, msg = _ensure_clean_main(cwd)
    if not ok:
        result["error"] = msg
        return result

    branch = _branch_name(proposal_id, source)
    ok, msg = _create_branch(cwd, branch)
    if not ok:
        result["error"] = msg
        return result
    result["branch"] = branch

    diff_text = proposal.get("proposed_diff") or ""
    target = proposal.get("proposed_diff_target") or ""
    ok, msg = _apply_diff(cwd, diff_text, target)
    if not ok:
        # Roll back the empty branch so we leave no garbage behind.
        _git(["checkout", "main"], cwd, check=False)
        _git(["branch", "-D", branch], cwd, check=False)
        result["error"] = msg
        result["branch"] = None
        return result

    ok, msg = _run_tests(cwd)
    if not ok:
        # Revert workdir, drop the branch.
        _git(["checkout", "."], cwd, check=False)
        _git(["checkout", "main"], cwd, check=False)
        _git(["branch", "-D", branch], cwd, check=False)
        result["error"] = msg
        result["branch"] = None
        return result

    ok, msg_or_sha = _commit(cwd, proposal_id)
    if not ok:
        result["error"] = msg_or_sha
        return result
    result["commit_sha"] = msg_or_sha
    result["success"] = True

    method = "permission_fix" if source == SOURCE_PERMISSION_FIX else "auto_apply"
    _append_applied_record(
        {
            "id": f"app_{proposal_id}",
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "proposal_id": proposal_id,
            "method": method,
            "branch": branch,
            "commit_sha": result["commit_sha"],
            "tests_passed": True,
            "rolled_back": False,
        }
    )

    _print_diff(cwd)
    _print_followup(branch, proposal_id)
    return result


def _cli() -> int:
    """Minimal CLI entry: `python apply-proposal.py <id> [source]`."""
    if len(sys.argv) < 2:
        sys.stderr.write(
            "usage: apply-proposal.py <proposal-id> [permission-fix|auto-apply]\n"
        )
        return 2
    proposal_id = sys.argv[1]
    source = sys.argv[2] if len(sys.argv) >= 3 else SOURCE_PERMISSION_FIX
    if source not in (SOURCE_PERMISSION_FIX, SOURCE_AUTO_APPLY):
        sys.stderr.write(
            f"source must be {SOURCE_PERMISSION_FIX!r} or {SOURCE_AUTO_APPLY!r}\n"
        )
        return 2
    result = apply_proposal(proposal_id, source)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
