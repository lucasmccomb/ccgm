"""Dispatcher handlers for the PreToolUse:Bash check chain.

These wrap the ALREADY-TESTED pure functions of the legacy per-process hooks
into the dispatcher's Result contract. They deliberately do NOT re-implement
any regex or branch-protection logic — each handler imports the legacy hook
module and calls its existing functions, so the dispatched path and the
legacy path share one source of truth and cannot drift.

Mapping (legacy hook → dispatcher check), in the order the legacy
settings.partial.json registers them for PreToolUse:Bash:

  enforce-git-workflow.py        → git_workflow_check        (hard_block, bypass-safe)
  auto-approve-bash.py           → destructive_check         (hard_block, bypass-safe, short-circuit)
                                   smart_rules_check          (hard_block/allow, bypass-safe)
                                   pattern_check              (deny/allow, NOT bypass-safe)
  port-check.py                  → port_advisory_check        (advisory only)
  agent-tracking-pre.py          → agent_tracking_check       (advisory only)
  check-migration-timestamps.py  → migration_timestamp_check  (hard_block, bypass-safe)
  check-careful.py               → force_push_main_check      (hard_block, bypass-safe)
                                   careful_check              (ask, NOT bypass-safe)

Precedence inside the dispatcher (DECISION_RANK) reproduces the legacy chain:
any hard_block beats deny beats allow beats ask. The destructive set is
marked short_circuit so it is emitted the instant it fires — identical to
auto-approve-bash.py running it ABOVE everything else.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
from contextlib import redirect_stderr

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_dispatcher as hd  # noqa: E402

# Where the legacy hook scripts live. Defaults to the installed location but
# is overridable (CCGM_HOOKS_DIR) so the test suite can point at the in-repo
# modules/hooks/hooks directory without installing.
_HOOKS_DIR = os.environ.get(
    "CCGM_HOOKS_DIR", os.path.expanduser("~/.claude/hooks")
)


def _load_hook(module_name: str, filename: str):
    """Import a legacy hook script by path under ~/.claude/hooks.

    The hooks are not on the import path (they are executable scripts), so we
    load them explicitly. Each is side-effect-free at import time (logic lives
    under `def main()` guarded by `if __name__ == '__main__'`).
    """
    path = os.path.join(_HOOKS_DIR, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _command(data: dict) -> str:
    return data.get("tool_input", {}).get("command", "") or ""


# ─── enforce-git-workflow.py ─────────────────────────────────────────
def git_workflow_check(data: dict) -> "hd.Result":
    """Protected-branch + issue-number enforcement (bypass-proof).

    The legacy hook calls hook_utils.hard_block() directly inside
    check_commit/check_push. We capture that exit-2 by running its main() in a
    controlled way: instead, call the underlying validators and translate a
    hard_block into a HARD_BLOCK Result. To avoid re-implementing the parsing,
    we reuse the module's own predicates and let it raise SystemExit(2), which
    we convert to a Result so the dispatcher owns emission.
    """
    egw = _load_hook("egw", "enforce-git-workflow.py")
    command = _command(data).strip()
    if data.get("tool_name", "") != "Bash" or not command:
        return hd.Result()
    if not (egw.is_commit_command(command) or egw.is_push_command(command)):
        return hd.Result()
    branch = egw.get_current_branch()
    if not branch:
        return hd.Result()

    # check_commit / check_push call hook_utils.hard_block() (→ SystemExit 2)
    # on a violation, writing the reason to stderr. Run them with stderr
    # captured so we can lift the reason into a Result rather than letting the
    # process die here — the dispatcher decides when to exit.
    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            if egw.is_commit_command(command):
                egw.check_commit(command, branch)
            elif egw.is_push_command(command):
                egw.check_push(command, branch)
    except SystemExit as exc:
        if exc.code == 2:
            return hd.Result(hd.HARD_BLOCK, buf.getvalue().rstrip("\n"))
        # Any non-2 exit from the validator is treated as no-decision.
        return hd.Result()
    # The validators may print a WARNING (ALLOW_MAIN_COMMIT bypass) to stderr
    # without blocking; surface it as advisory.
    warned = buf.getvalue()
    if warned.strip():
        return hd.Result(advisory=warned.rstrip("\n"))
    return hd.Result()


# ─── auto-approve-bash.py ────────────────────────────────────────────
def destructive_check(data: dict) -> "hd.Result":
    """Curated destructive set (whole-disk/root destruction). Bypass-proof."""
    aab = _load_hook("aab", "auto-approve-bash.py")
    command = _command(data)
    if data.get("tool_name", "") != "Bash" or not command:
        return hd.Result()
    label, reason = aab.check_destructive(command)
    if label:
        return hd.Result(hd.HARD_BLOCK, reason or "destructive command blocked")
    return hd.Result()


def force_branch_delete_check(data: dict) -> "hd.Result":
    """`git branch` force-delete: hard-block naming the segment and the way out.

    Bypass-safe on purpose. In bypass mode the pattern check never runs, so
    without this the only message an agent sees is Claude Code's own generic
    "Permission to use Bash with command <whole chain> has been denied" —
    which reads as if worktree removal were blocked (issue #907).
    """
    aab = _load_hook("aab", "auto-approve-bash.py")
    command = _command(data)
    if data.get("tool_name", "") != "Bash" or not command:
        return hd.Result()
    segment, reason = aab.check_force_branch_delete(command)
    if segment:
        return hd.Result(hd.HARD_BLOCK, reason or "force branch delete blocked")
    return hd.Result()


def smart_rules_check(data: dict) -> "hd.Result":
    """git reset --hard smart-rule: allow remote-ref resets, hard-block others."""
    aab = _load_hook("aab", "auto-approve-bash.py")
    command = _command(data)
    if data.get("tool_name", "") != "Bash" or not command:
        return hd.Result()
    decision, reason = aab.check_smart_rules(command)
    if decision == "hard_block":
        return hd.Result(hd.HARD_BLOCK, reason or "destructive smart-rule matched")
    if decision == "allow":
        return hd.Result(hd.ALLOW, reason or "smart-rule allow")
    return hd.Result()


def pattern_check(data: dict) -> "hd.Result":
    """settings.json allow/deny pattern matching, per-segment (#660 fix).

    NOT bypass-safe: in bypass mode the dispatcher skips this check, exactly
    as auto-approve-bash.py exits 0 before pattern matching when bypass is on.
    """
    aab = _load_hook("aab", "auto-approve-bash.py")
    command = _command(data)
    if data.get("tool_name", "") != "Bash" or not command:
        return hd.Result()
    allow_patterns, deny_patterns = aab.load_settings()
    decision, reason = aab.check_pattern_decision(command, allow_patterns, deny_patterns)
    if decision == "deny":
        return hd.Result(hd.DENY, reason or "")
    if decision == "allow":
        return hd.Result(hd.ALLOW, reason or "")
    return hd.Result()


# ─── port-check.py ───────────────────────────────────────────────────
def port_advisory_check(data: dict) -> "hd.Result":
    """Dev-server port-allocation warnings. Advisory only, never blocks.

    NOT bypass-safe: port-check.py returns silently in bypass mode.
    """
    pc = _load_hook("pc", "port-check.py")
    if data.get("tool_name", "") != "Bash":
        return hd.Result()
    command = _command(data)
    if not pc.is_dev_server_command(command):
        return hd.Result()
    # port-check.py writes warnings to stderr inside main(). Run main() with
    # stderr captured and surface the text as advisory. main() never emits a
    # permission decision, so nothing else leaks.
    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            pc.main_with_data(data) if hasattr(pc, "main_with_data") else _run_port_main(pc, data)
    except SystemExit:
        pass
    text = buf.getvalue()
    if text.strip():
        return hd.Result(advisory=text.rstrip("\n"))
    return hd.Result()


def _run_port_main(pc, data: dict) -> None:
    """port-check.py.main() reads its own stdin; feed it our envelope."""
    import json
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(data))
    try:
        pc.main()
    finally:
        sys.stdin = saved


# ─── agent-tracking-pre.py ───────────────────────────────────────────
def agent_tracking_check(data: dict) -> "hd.Result":
    """Multi-agent issue-claim warnings. Advisory only, never blocks."""
    at = _load_hook("atp", "agent-tracking-pre.py")
    if data.get("tool_name", "") != "Bash":
        return hd.Result()
    import json
    buf_out = io.StringIO()
    saved_in, saved_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(data))
    sys.stdout = buf_out
    try:
        at.main()
    except SystemExit:
        pass
    finally:
        sys.stdin, sys.stdout = saved_in, saved_out
    # agent-tracking-pre emits its warnings as JSON with only a
    # permissionDecisionReason (no permissionDecision) — that is advisory by
    # Claude Code's contract. Surface it as advisory text.
    text = buf_out.getvalue()
    if text.strip():
        return hd.Result(advisory=text.rstrip("\n"))
    return hd.Result()


# ─── check-migration-timestamps.py ───────────────────────────────────
def migration_timestamp_check(data: dict) -> "hd.Result":
    """Duplicate Supabase migration timestamps. Data-integrity hard_block."""
    cmt = _load_hook("cmt", "check-migration-timestamps.py")
    import json
    buf = io.StringIO()
    saved_in = sys.stdin
    sys.stdin = io.StringIO(json.dumps(data))
    try:
        with redirect_stderr(buf):
            cmt.main()
    except SystemExit as exc:
        if exc.code == 2:
            return hd.Result(hd.HARD_BLOCK, buf.getvalue().rstrip("\n"))
    finally:
        sys.stdin = saved_in
    return hd.Result()


# ─── check-careful.py ────────────────────────────────────────────────
def force_push_main_check(data: dict) -> "hd.Result":
    """Force-push to main. Bypass-proof hard_block (gated by ALLOW_MAIN_COMMIT)."""
    cc = _load_hook("cc", "check-careful.py")
    if data.get("tool_name", "") != "Bash":
        return hd.Result()
    command = _command(data)
    if not command:
        return hd.Result()
    if cc._is_force_push_to_main(command) and os.environ.get("ALLOW_MAIN_COMMIT") != "1":
        return hd.Result(
            hd.HARD_BLOCK,
            "BLOCKED: force-pushing to `main` overwrites shared history. "
            "If this is truly intended (recovering from a bad merge, etc.), "
            "re-run with `ALLOW_MAIN_COMMIT=1` set.",
        )
    return hd.Result()


def careful_check(data: dict) -> "hd.Result":
    """Destructive-command prompt (ask). NOT bypass-safe."""
    cc = _load_hook("cc", "check-careful.py")
    if data.get("tool_name", "") != "Bash":
        return hd.Result()
    command = _command(data)
    if not command:
        return hd.Result()
    is_destructive, reason = cc.check_careful(command)
    if is_destructive:
        return hd.Result(hd.ASK, reason)
    return hd.Result()
