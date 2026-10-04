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

Validation gate (#1099 Phase 2.3): `validate(proposal)` is the one check the
nightly drafting path and `apply_proposal()` both run before a proposal is
shown or applied.
"""
from __future__ import annotations

import datetime as _dt
import glob
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile

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


def fix_surface(proposal: dict) -> str:
    """The proposal's fix surface: check, rule, tool or access.

    Proposals written before fix_surface existed are in the field with no
    such key; they were all config or doc edits, so a missing value is
    `rule`.
    """
    return proposal.get("fix_surface") or "rule"


def demonstration_problem(demo: dict | None) -> str | None:
    """Why a failing demonstration is unacceptable, or None if it holds.

    A new check counts only after it ran clean, failed on a deliberate
    violation, and the violation was reverted.
    """
    if not isinstance(demo, dict):
        return "no demonstration supplied"
    if not demo.get("command") or not demo.get("violation"):
        return "demonstration needs `command` and `violation`"
    if demo.get("clean_exit") != 0:
        return "check did not pass on clean code (clean_exit must be 0)"
    violation_exit = demo.get("violation_exit")
    if not isinstance(violation_exit, int) or violation_exit == 0:
        return "check did not fail on the violation (violation_exit must be non-zero)"
    if demo.get("reverted") is not True:
        return "violation was not reverted"
    return None


# ---------------------------------------------------------------------
# Validation gate. Runs against a throwaway copy of origin/main, so the
# source repo's working tree, index, refs and worktree list are never touched.
# ---------------------------------------------------------------------

DEFAULT_RULE_BUDGET_LINES = 20       # config: rule_budget_lines_per_week
DEFAULT_CHECK_TIMEOUT_SECONDS = 120  # config: validation_timeout_seconds
BUDGET_WINDOW_DAYS = 7


class _Unavailable(Exception):
    """A check could not run (missing script, timeout, no archive). Not a verdict."""


def _sibling(filename: str, name: str):
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clean_env() -> dict:
    env = os.environ.copy()
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(var, None)
    return env


def _run_limited(cmd: list[str], cwd: str, timeout: int, input_bytes: bytes | None = None):
    """Run cmd in its own process group and kill the group on timeout.

    Returns (returncode, output bytes). Raises _Unavailable on timeout or when
    the command cannot start.
    """
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=_clean_env(), start_new_session=True,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise _Unavailable(f"cannot run {cmd[0]}: {exc}")
    try:
        out, _ = proc.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        raise _Unavailable(f"{cmd[0]} timed out after {timeout}s")
    return proc.returncode, out


def _gate_config() -> dict:
    try:
        path = _sibling("module-index.py", "autoheal_module_index").config_path()
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _int_setting(cfg: dict, key: str, default: int) -> int:
    value = cfg.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _origin_show(repo: str, path: str, timeout: int) -> str | None:
    """Text of `path` at origin/main, or None when it is not there."""
    rc, out = _run_limited(["git", "-C", repo, "show", f"origin/main:{path}"], repo, timeout)
    return out.decode("utf-8", "replace") if rc == 0 else None


def _is_rule_path(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 4 and parts[0] == "modules" and parts[2] == "rules" and parts[3].endswith(".md")


def _has_paths_frontmatter(text: str) -> bool:
    """True when the file opens with YAML frontmatter holding a `paths:` key."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if line.startswith("paths:"):
            return True
    return False


def _added_by_file(diff: str) -> dict:
    """{repo-relative path: number of added lines} from a unified diff."""
    counts: dict = {}
    current = None
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            name = line[4:].split("\t")[0].strip()
            current = name[2:] if name.startswith("b/") else None
            if current is not None:
                counts.setdefault(current, 0)
        elif line.startswith("+") and current is not None:
            counts[current] += 1
    return counts


def _always_loaded_added(repo: str, diff: str, timeout: int) -> int:
    """Lines a diff adds to always-loaded rule files (rules/*.md without `paths:`)."""
    total = 0
    for path, added in _added_by_file(diff).items():
        if not _is_rule_path(path):
            continue
        text = _origin_show(repo, path, timeout)
        if text is not None and _has_paths_frontmatter(text):
            continue
        total += added
    return total


def _parse_ts(value, fallback):
    try:
        ts = _dt.datetime.fromisoformat(str(value))
    except ValueError:
        return fallback
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


def _jsonl_rows(directory: str):
    """(record, date from the file name or None) for every row of every *.jsonl."""
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        stem = os.path.basename(path)[: -len(".jsonl")]
        try:
            day = _dt.datetime.strptime(stem, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            day = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        yield rec, day
        except OSError:
            continue


def _recent_rule_lines(repo: str, exclude_id: str, now: _dt.datetime, timeout: int) -> int:
    """Always-loaded rule lines added by ready or applied proposals in the last 7 days."""
    cutoff = now - _dt.timedelta(days=BUDGET_WINDOW_DAYS)
    rows: dict = {}
    for rec, day in _jsonl_rows(_proposals_dir()):
        if isinstance(rec.get("id"), str):
            rows[rec["id"]] = (rec, _parse_ts(rec.get("generated_at"), day))
    counted = {pid for pid, (rec, ts) in rows.items()
               if rec.get("state") in ("ready", "applied") and ts is not None and ts >= cutoff}
    for rec, day in _jsonl_rows(_applied_dir()):
        ts = _parse_ts(rec.get("ts"), day)
        if rec.get("proposal_id") in rows and ts is not None and ts >= cutoff and not rec.get("rolled_back"):
            counted.add(rec["proposal_id"])
    total = 0
    for pid in counted - {exclude_id}:
        rec = rows[pid][0]
        total += _always_loaded_added(repo, rec.get("diff") or rec.get("proposed_diff") or "", timeout)
    return total


def _check_passes(tree: str, name: str, timeout: int) -> bool:
    """Run tests/<name> in the copy; True on exit 0."""
    script = os.path.join(tree, "tests", name)
    if not os.path.isfile(script):
        raise _Unavailable(f"tests/{name} missing in origin/main")
    rc, _ = _run_limited(["bash", script], tree, timeout)
    return rc == 0


def validate(proposal: dict, repo_root: str | None = None, now: _dt.datetime | None = None) -> tuple[bool, str]:
    """Gate a proposal before it is shown or applied: (ok, reason).

    reason is "" on success, else one of path_not_candidate, anchor_missing,
    rule_budget, apply_conflict, personal_data, module_tests, or
    validation_unavailable (the source repo or a check could not run, which
    says nothing about the proposal). A row with no diff, such as an issue
    proposal, passes.

    Checks, cheapest first, all against origin/main of the CCGM source repo:
      1. rule_insert only: target is a modules/*/rules/*.md file in origin/main
         and the anchor heading is in it.
      2. Rule budget: lines this diff adds to always-loaded rule files (no
         `paths:` frontmatter) plus those of every ready or applied proposal
         in the last 7 days stay within `rule_budget_lines_per_week`
         (config, default 20).
      3. The diff applies to a throwaway copy of origin/main (git archive
         into a temp dir; the repo itself is only read).
      4. tests/test-no-personal-data.sh passes in the copy with the diff applied.
      5. tests/test-modules.sh passes in the copy.
    Each command is capped by `validation_timeout_seconds` (config, default 120).
    """
    diff = proposal.get("diff") or proposal.get("proposed_diff") or ""
    if not diff.strip():
        return True, ""
    cfg = _gate_config()
    timeout = _int_setting(cfg, "validation_timeout_seconds", DEFAULT_CHECK_TIMEOUT_SECONDS)
    budget = _int_setting(cfg, "rule_budget_lines_per_week", DEFAULT_RULE_BUDGET_LINES)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    try:
        if repo_root is None:
            repo_root, _how = _sibling("module-index.py", "autoheal_module_index").resolve_source_repo()
        if not repo_root or not os.path.isdir(repo_root):
            return False, "validation_unavailable"
        rc, _ = _run_limited(["git", "-C", repo_root, "rev-parse", "--verify", "-q", "origin/main"],
                             repo_root, timeout)
        if rc != 0:
            return False, "validation_unavailable"

        if proposal.get("kind") == "rule_insert":
            target = proposal.get("target") or ""
            text = _origin_show(repo_root, target, timeout) if _is_rule_path(target) else None
            if text is None:
                return False, "path_not_candidate"
            found = _sibling("draft_proposals.py", "autoheal_draft").find_heading(
                text.split("\n"), proposal.get("anchor") or "")
            if found is None:
                return False, "anchor_missing"

        added = _always_loaded_added(repo_root, diff, timeout)
        if added and added + _recent_rule_lines(repo_root, str(proposal.get("id")), now, timeout) > budget:
            return False, "rule_budget"

        with tempfile.TemporaryDirectory(prefix="autoheal-validate-") as tree:
            rc, archive = _run_limited(["git", "-C", repo_root, "archive", "origin/main"], repo_root, timeout)
            if rc != 0:
                raise _Unavailable("git archive failed")
            rc, _ = _run_limited(["tar", "-x", "-C", tree], tree, timeout, input_bytes=archive)
            if rc != 0:
                raise _Unavailable("tar extract failed")
            # A private repo in the copy stops `git apply` from resolving paths against an
            # enclosing repository, and gives the repo's own checks a git tree to inspect.
            _run_limited(["git", "init", "-q"], tree, timeout)
            payload = diff.encode("utf-8")
            for args in (["--check", "-"], ["-"]):
                rc, _ = _run_limited(["git", "apply", *args], tree, timeout, input_bytes=payload)
                if rc != 0:
                    return False, "apply_conflict"
            if not _check_passes(tree, "test-no-personal-data.sh", timeout):
                return False, "personal_data"
            if not _check_passes(tree, "test-modules.sh", timeout):
                return False, "module_tests"
    except _Unavailable:
        return False, "validation_unavailable"
    return True, ""


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


def apply_proposal(
    proposal_id: str,
    source: str = SOURCE_PERMISSION_FIX,
    demonstration: dict | None = None,
) -> dict:
    """
    Apply a proposal to the canonical CCGM clone source.

    Args:
        proposal_id: id of the proposal in today's proposals.jsonl.
        source: "permission-fix" or "auto-apply". Determines branch
                shape and the `method` field in the audit record.
        demonstration: required when the proposal's fix_surface is
                "check": {command, clean_exit, violation, violation_exit,
                reverted}. Recorded in the audit record.

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

    if proposal.get("state", "ready") != "ready":
        result["error"] = f"proposal {proposal_id} is {proposal.get('state')}, not ready"
        return result

    if fix_surface(proposal) == "check":
        problem = demonstration_problem(demonstration)
        if problem:
            result["error"] = f"check proposal needs a failing demonstration: {problem}"
            return result

    cwd = _resolve_clone_root()
    if cwd is None:
        result["error"] = "could not resolve canonical CCGM clone root"
        return result

    ok, reason = validate(proposal, repo_root=cwd)
    # An unavailable gate does not block: the test gate below still runs on the clone.
    if not ok and reason != "validation_unavailable":
        result["error"] = f"validation failed: {reason}"
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
            "fix_surface": fix_surface(proposal),
            "demonstration": demonstration,
        }
    )

    _print_diff(cwd)
    _print_followup(branch, proposal_id)
    return result


def _cli() -> int:
    """CLI: `python apply-proposal.py <id> [source] [--demonstration <file>]`."""
    args = sys.argv[1:]
    demonstration = None
    if "--demonstration" in args:
        i = args.index("--demonstration")
        try:
            with open(args[i + 1], "r", encoding="utf-8") as fh:
                demonstration = json.load(fh)
        except (IndexError, OSError, ValueError) as exc:
            sys.stderr.write(f"cannot read --demonstration file: {exc}\n")
            return 2
        del args[i : i + 2]
    if not args:
        sys.stderr.write(
            "usage: apply-proposal.py <proposal-id> [permission-fix|auto-apply] "
            "[--demonstration <file.json>]\n"
        )
        return 2
    proposal_id = args[0]
    source = args[1] if len(args) >= 2 else SOURCE_PERMISSION_FIX
    if source not in (SOURCE_PERMISSION_FIX, SOURCE_AUTO_APPLY):
        sys.stderr.write(
            f"source must be {SOURCE_PERMISSION_FIX!r} or {SOURCE_AUTO_APPLY!r}\n"
        )
        return 2
    result = apply_proposal(proposal_id, source, demonstration)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
