#!/usr/bin/env python3
"""autoheal-review.py - the code behind /autoheal-review (#1099 Phase 3.2).

/autoheal-review is the one place a user accepts a fix. The command file asks
the questions; this script does every step that is plain computation:

  list [--limit 5] [--id ID] [--now ISO]
        Ready ledger rows, oldest first, at most --limit. Prints JSON:
        {"total_ready", "shown", "items": [{"id", "kind", "question",
        "edit_question", "reject_question"}]}. Each payload is a complete
        AskUserQuestion input that carries its own evidence (signature, counts,
        sessions, dates, two redacted samples, target file, anchor heading, the
        exact diff in the Apply preview), so the ask-context gate passes it.
  apply ID [--insert-file F | --insert-text T]
        rule_insert: re-run validate(), open a temporary worktree of the CCGM
        source repo on branch autoheal/<id> from origin/main, commit with the
        Autoheal-Id and Autoheal-Signature trailers, push, open a PR, wait for
        checks, squash-merge it (never --admin). The ledger row becomes
        `applied` with the PR URL, merge SHA, merged_at and baseline_rate.
        issue: file a GitHub issue on the source repo with the evidence.
        A failure after the PR exists leaves the PR open and the row `ready`
        with an `apply_error`; a retry merges the same PR.
        The source repo's own working tree is never touched.
        --auto marks the row applied_by auto (the nightly auto-apply step).
  reject ID --reason TEXT    state rejected, signature suppressed for 90 days
  snooze ID [--days 14]      state snoozed until now + days
  revert ID [--reason T] [--auto]
        Undo an applied or measured rule_insert: a temporary worktree on
        autoheal/revert-<id> from origin/main, `git revert` of the commit carrying
        `Autoheal-Id: <id>` (the row's merge_sha when it is on origin/main),
        commit with an Autoheal-Revert trailer, push, PR, checks, squash-merge,
        delete the remote branch. The row becomes `reverted`. A failure keeps the
        row's state and records revert_error.
  redraft ID                 a measured row stops covering its signature, so the
                             next nightly run drafts it again; the merged rule stays

Prints one JSON object per call; exit 0 when "ok" is true, 1 otherwise.
Tests put a fake `gh` first on PATH and point the source repo at a fixture.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

LIST_LIMIT = 5
REJECT_DAYS = 90
SNOOZE_DAYS = 14
BASELINE_DAYS = 14
MAX_SAMPLES_SHOWN = 2
CHECKS_TIMEOUT_SECONDS = 1800
GIT_TIMEOUT_SECONDS = 300
SUPPORTED_KINDS = ("rule_insert", "issue")
# Drop reasons that say the proposal no longer fits main (the row is dropped and the
# aggregator redrafts it after a cooldown). Anything else leaves the row ready.
CONTENT_FAILURES = ("path_not_candidate", "anchor_missing", "apply_conflict",
                    "personal_data", "module_tests")

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")


class Failure(Exception):
    """A step failed; the message goes to the user and, when the row is known, to apply_error."""


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger():
    return _load(os.path.join(_LIB, "ledger.py"), "autoheal_ledger")


def _drafts():
    return _load(os.path.join(_LIB, "draft_proposals.py"), "autoheal_draft")


def _module_index():
    return _load(os.path.join(_LIB, "module-index.py"), "autoheal_module_index")


def _aggregate():
    return _load(os.path.join(_HERE, "autoheal-aggregate.py"), "autoheal_aggregate")


def _apply_lib():
    return _load(os.path.join(_LIB, "apply-proposal.py"), "autoheal_apply")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_now(value: str | None) -> dt.datetime:
    if not value:
        return _now()
    when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------
# Subprocess helpers.
# ---------------------------------------------------------------------

def _env() -> dict:
    env = os.environ.copy()
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(var, None)
    return env


def run(cmd: list, cwd: str, timeout: int = GIT_TIMEOUT_SECONDS, stdin: str | None = None):
    """(returncode, combined output). A missing binary or a timeout is rc 127 / 124."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=_env(), input=stdin, text=True, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out after {timeout}s"
    return proc.returncode, proc.stdout or ""


def _tail(text: str, limit: int = 600) -> str:
    text = " ".join((text or "").split())
    return text[-limit:]


def source_repo() -> str:
    root, how = _module_index().resolve_source_repo()
    if not root:
        raise Failure(f"cannot find the CCGM source repo: {how}")
    return root


def repo_slug(root: str) -> str:
    rc, out = run(["git", "-C", root, "remote", "get-url", "origin"], root, 30)
    url = out.strip() if rc == 0 else ""
    match = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
    return match.group(1) if match else (url or "the CCGM source repo")


def signature_of(row: dict) -> tuple:
    return (str(row.get("tool_name") or ""), str(row.get("cmd_head") or ""),
            str(row.get("error_class") or ""))


def signature_text(row: dict) -> str:
    return "|".join(signature_of(row))


# ---------------------------------------------------------------------
# list: question payloads.
# ---------------------------------------------------------------------

def _evidence(row: dict) -> dict:
    ev = row.get("evidence")
    return ev if isinstance(ev, dict) else {}


def _evidence_text(row: dict) -> str:
    ev = _evidence(row)
    tool, head, cls = signature_of(row)
    count = ev.get("count", row.get("occurrence_count"))
    lines = [
        f"Signature: tool {tool}, command head {head or '(none)'}, error class {cls}.",
        f"Seen {count} times in {ev.get('sessions')} sessions across {ev.get('days')} days "
        f"({ev.get('first_seen')} to {ev.get('last_seen')}).",
    ]
    rate = ev.get("rate_per_100_calls")
    if isinstance(rate, (int, float)):
        lines.append(f"That is {rate:.1f} failures per 100 {tool} calls.")
    samples = [s for s in (ev.get("samples") or []) if isinstance(s, str)][:MAX_SAMPLES_SHOWN]
    if samples:
        lines.append("Sample errors (secrets redacted):")
        lines += [f"- {s}" for s in samples]
    return "\n".join(lines)


def _until(now: dt.datetime, days: int) -> str:
    return (now + dt.timedelta(days=days)).date().isoformat()


def _option(label: str, description: str, preview: str | None = None) -> dict:
    out = {"label": label, "description": description}
    if preview:
        out["preview"] = preview
    return out


def _reject_question(row: dict, now: dt.datetime) -> dict:
    until = _until(now, REJECT_DAYS)
    tool, head, cls = signature_of(row)
    text = (f"Why reject the autoheal fix for {tool} `{head}` ({cls})? "
            f"It fired {_evidence(row).get('count', row.get('occurrence_count'))} times, and the fix "
            f"would change {row.get('target') or row.get('module') or 'the CCGM source repo'}. "
            f"Rejecting suppresses this signature until {until}. "
            "Pick the closest reason, or type your own under Other.")
    reasons = [
        ("Wrong fix", "The rule would not prevent these failures or says the wrong thing."),
        ("Not a real problem", "These failures are expected or harmless; no rule needed."),
        ("Already covered", "A rule or hook that handles this already exists elsewhere."),
        ("Too noisy", "The fix would add more prompt text than the failures cost."),
    ]
    return {"questions": [{
        "question": text, "header": "Reject reason", "multiSelect": False,
        "options": [_option(label, f"{desc} Recorded as the reason; suppressed until {until}.")
                    for label, desc in reasons]}]}


def _edit_question(row: dict, repo: str) -> dict:
    tool, head, cls = signature_of(row)
    text = (f"Type the replacement lines (markdown, at most 8) for the autoheal fix for {tool} "
            f"`{head}` ({cls}), which adds text under the heading \"{row.get('anchor')}\" in "
            f"{row.get('target')}. The proposed lines are:\n{row.get('insert_markdown')}\n"
            "Type your lines under Other. They are re-validated against origin/main before anything is pushed.")
    return {"questions": [{
        "question": text, "header": "Edit fix", "multiSelect": False,
        "options": [
            _option("Back to the fix", "Discard the edit. The fix stays ready and I show the original question again."),
            _option("Skip for now", f"Leave the fix ready without deciding. Nothing is pushed to {repo}; "
                                    "it shows up again in the next /autoheal-review."),
        ]}]}


def _question(row: dict, repo: str, position: int, total: int, now: dt.datetime) -> dict:
    kind = row.get("kind")
    snooze_until = _until(now, SNOOZE_DAYS)
    reject_until = _until(now, REJECT_DAYS)
    head = f"Autoheal fix {position} of {total}. "
    if kind == "issue":
        text = (head + f"{row.get('title')}. The {row.get('module')} hook keeps refusing the same call, "
                "and a hook change needs a person, so autoheal proposes an issue instead of a rule.\n"
                + _evidence_text(row)
                + f"\nApply files the issue on {repo}; the Apply preview holds its title and body.")
        preview = f"{row.get('issue_title')}\n\n{row.get('issue_body')}"
        options = [
            _option("Apply", f"Files this issue on {repo} with the evidence. No code changes.", preview),
            _option("Reject", f"Records your reason; this signature is suppressed until {reject_until}."),
            _option("Snooze 14d", f"Hidden until {snooze_until}; it returns to /autoheal-review then."),
        ]
    else:
        text = (head + f"{row.get('title')}.\n" + _evidence_text(row)
                + f"\nProposed fix: add lines under the heading \"{row.get('anchor')}\" in "
                  f"{row.get('target')} (repo {repo}). The Apply preview is the exact diff.")
        options = [
            _option("Apply", f"Opens a PR to {repo}, waits for checks, then squash-merges it (no admin override). "
                             "The failure rate is measured for 14 days afterward.", row.get("diff")),
            _option("Edit then apply", "You type replacement lines (max 8). They are re-validated, "
                                       f"then the same PR and squash-merge to {repo} as Apply."),
            _option("Reject", f"Records your reason; this signature is suppressed until {reject_until}."),
            _option("Snooze 14d", f"Hidden until {snooze_until}; it returns to /autoheal-review then."),
        ]
    return {"questions": [{"question": text, "header": f"Fix {position} of {total}",
                           "multiSelect": False, "options": options}]}


def _sort_key(row: dict) -> str:
    return str(row.get("generated_at") or row.get("source_day") or "")


def cmd_list(args) -> dict:
    led = _ledger()
    now = _parse_now(args.now)
    rows = [r for r in led.ready_rows(now) if r.get("kind") in SUPPORTED_KINDS]
    if args.id:
        rows = [r for r in rows if r.get("id") == args.id]
    rows.sort(key=_sort_key)
    try:
        repo = repo_slug(source_repo())
    except Failure:
        repo = "the CCGM source repo"
    shown = rows[:max(0, args.limit)]
    items = []
    for n, row in enumerate(shown, 1):
        item = {"id": row.get("id"), "kind": row.get("kind"),
                "question": _question(row, repo, n, len(shown), now),
                "reject_question": _reject_question(row, now)}
        if row.get("kind") == "rule_insert":
            item["edit_question"] = _edit_question(row, repo)
        items.append(item)
    return {"ok": True, "total_ready": len(rows), "shown": len(items), "items": items}


# ---------------------------------------------------------------------
# apply.
# ---------------------------------------------------------------------

def _build_edit(root: str, row: dict, text: str) -> tuple:
    """(insert_markdown, diff) for replacement text, built from origin/main."""
    dp = _drafts()
    target = row.get("target") or ""
    rc, old = run(["git", "-C", root, "show", f"origin/main:{target}"], root, 60)
    if rc != 0:
        raise Failure(f"path_not_candidate: {target} is not on origin/main")
    lines = [ln.rstrip() for ln in text.strip("\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not any(ln.strip() for ln in lines):
        raise Failure("edit is empty")
    if len(lines) > dp.MAX_INSERT_LINES:
        raise Failure(f"edit has {len(lines)} lines; the limit is {dp.MAX_INSERT_LINES}")
    new = dp.insert_under_heading(old, row.get("anchor") or "", lines)
    if new is None:
        raise Failure(f"anchor_missing: heading \"{row.get('anchor')}\" is not in {target} on origin/main")
    return "\n".join(lines), dp.unified_diff(target, old, new)


def _trailers(row: dict) -> str:
    return f"Autoheal-Id: {row['id']}\nAutoheal-Signature: {signature_text(row)}"


def _commit_subject(row: dict) -> str:
    # The convention of lib/apply-proposal.py; enforce-git-workflow.py accepts `#auto:`.
    return f"#auto: apply autoheal proposal {row['id']}"


def _body(row: dict) -> str:
    return "\n".join([
        f"Adds a rule under \"{row.get('anchor')}\" in {row.get('target')}.",
        "",
        _evidence_text(row),
        "",
        _trailers(row),
    ])


def _checks_timeout() -> int:
    try:
        with open(_module_index().config_path(), "r", encoding="utf-8") as fh:
            value = json.load(fh).get("apply_checks_timeout_seconds")
    except (OSError, ValueError, AttributeError):
        value = None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else CHECKS_TIMEOUT_SECONDS


def _wait_for_checks(url: str, root: str) -> None:
    timeout = _checks_timeout()
    rc, out = run(["gh", "pr", "checks", url, "--watch"], root, timeout)
    if rc == 0 or "no checks reported" in out:
        return
    if rc == 124:
        raise Failure(f"checks still running after {timeout}s: {url}")
    raise Failure(f"checks failed: {_tail(out)}")


def _merge(url: str, root: str, subject: str, body: str) -> None:
    cmd = ["gh", "pr", "merge", url, "--squash", "--subject", subject, "--body", body]
    rc, out = run(cmd, root)
    if rc != 0 and re.search(r"behind|not up to date|out of date", out, re.I):
        rc2, out2 = run(["gh", "pr", "update-branch", url, "--rebase"], root)
        if rc2 != 0:
            raise Failure(f"branch is behind and update-branch failed: {_tail(out2)}")
        _wait_for_checks(url, root)
        rc, out = run(cmd, root)
    if rc != 0:
        raise Failure(f"merge refused: {_tail(out)}")


def _delete_remote_branch(root: str, branch: str) -> None:
    """Remove the merged branch from origin (the repo does not delete head branches).

    `git push --delete` changes only the remote; the source repo's checkout stays as it is.
    A failure is logged and never fails the apply: the merge already happened.
    """
    rc, out = run(["git", "-C", root, "push", "origin", "--delete", branch], root, 120)
    if rc != 0:
        sys.stderr.write(f"autoheal-review: could not delete origin/{branch}: {_tail(out)}\n")


def _baseline(row: dict, merged: dt.datetime) -> dict:
    agg = _aggregate()
    day = merged.date()
    start, end = day - dt.timedelta(days=BASELINE_DAYS), day - dt.timedelta(days=1)
    stats = agg.signature_rate(agg.autoheal_dir(), signature_of(row), start, end)
    return {"baseline_rate": stats["rate_per_100_calls"],
            "baseline_occurrences": stats["occurrences"],
            "baseline_calls": stats["calls"],
            "baseline_window": [start.isoformat(), end.isoformat()]}


def _open_pr(root: str, branch: str, prepare, subject: str, body: str) -> tuple:
    """Worktree on `branch` from origin/main -> prepare(worktree) stages the change ->
    commit -> push -> PR. Returns (pr_url, commit_sha). Apply and revert share it."""
    tmp = tempfile.mkdtemp(prefix="autoheal-apply-")
    wt = os.path.join(tmp, "wt")
    added = False
    try:
        rc, out = run(["git", "-C", root, "worktree", "add", "-B", branch, wt, "origin/main"], root)
        if rc != 0:
            raise Failure(f"worktree add failed: {_tail(out)}")
        added = True
        prepare(wt)
        message = subject + "\n\n" + body + "\n"
        rc, out = run(["git", "commit", "-q", "-F", "-"], wt, stdin=message)
        if rc != 0:
            raise Failure(f"commit failed: {_tail(out)}")
        rc, sha = run(["git", "rev-parse", "HEAD"], wt, 60)
        # The branch name is the signature id, so a branch from an earlier, merged apply of the
        # same signature may still sit on origin. Replace exactly that tip and nothing newer.
        rc, listed = run(["git", "ls-remote", "--heads", "origin", branch], wt, 60)
        old_tip = listed.split()[0] if rc == 0 and listed.strip() else ""
        push = ["git", "push", "origin", branch]
        if old_tip:
            push.insert(2, f"--force-with-lease=refs/heads/{branch}:{old_tip}")
        rc, out = run(push, wt)
        if rc != 0:
            raise Failure(f"push failed: {_tail(out)}")
        rc, out = run(["gh", "pr", "create", "--base", "main", "--head", branch,
                       "--title", subject, "--body", body], wt)
        url = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""
        if not url.startswith("http"):
            raise Failure(f"gh pr create failed: {_tail(out)}")
        return url, sha.strip()
    finally:
        if added:
            run(["git", "-C", root, "worktree", "remove", "--force", wt], root, 60)
        run(["git", "-C", root, "worktree", "prune"], root, 60)
        run(["git", "-C", root, "branch", "-D", branch], root, 60)
        shutil.rmtree(tmp, ignore_errors=True)


def _fail(led, row: dict, message: str, **fields) -> dict:
    led.set_state(row["id"], "ready", apply_error=message, **fields)
    out = {"ok": False, "id": row["id"], "state": "ready", "error": message}
    out.update({k: v for k, v in fields.items() if k in ("pr_url",)})
    return out


def _apply_rule(led, row: dict, insert_text: str | None, applied_by: str = "review") -> dict:
    root = source_repo()
    rc, out = run(["git", "-C", root, "fetch", "origin", "main"], root)
    if rc != 0:
        return _fail(led, row, f"fetch failed: {_tail(out)}")
    extra: dict = {}
    pr_url = row.get("pr_url")
    if insert_text is not None:
        try:
            insert, diff = _build_edit(root, row, insert_text)
        except Failure as exc:
            return {"ok": False, "id": row["id"], "state": row.get("state"), "error": str(exc)}
        row = dict(row, insert_markdown=insert, diff=diff)
        extra = {"edited": True, "insert_markdown": insert, "diff": diff}
    if not pr_url:
        ok, reason = _apply_lib().validate(row, repo_root=root)
        if not ok:
            message = f"validation failed: {reason}"
            if insert_text is not None:
                # The user's text failed, not the stored proposal: leave the row as it is.
                return {"ok": False, "id": row["id"], "state": row.get("state"), "error": message}
            if reason in CONTENT_FAILURES:
                led.set_state(row["id"], "dropped", drop_reason=reason, apply_error=message)
                return {"ok": False, "id": row["id"], "state": "dropped", "error": message}
            return _fail(led, row, message)
        branch = f"autoheal/{row['id']}"

        def prepare(wt: str) -> None:
            rc, out = run(["git", "apply", "-"], wt, stdin=row["diff"])
            if rc != 0:
                raise Failure(f"apply_conflict: {_tail(out)}")
            rc, out = run(["git", "add", "--", row["target"]], wt)
            if rc != 0:
                raise Failure(f"git add failed: {_tail(out)}")

        try:
            pr_url, commit_sha = _open_pr(root, branch, prepare, _commit_subject(row), _body(row))
        except Failure as exc:
            return _fail(led, row, str(exc))
        extra.update({"branch": branch, "commit_sha": commit_sha})
    try:
        _wait_for_checks(pr_url, root)
        _merge(pr_url, root, _commit_subject(row), _body(row))
    except Failure as exc:
        return _fail(led, row, str(exc), pr_url=pr_url, **extra)
    _delete_remote_branch(root, f"autoheal/{row['id']}")
    _, sha = run(["gh", "pr", "view", pr_url, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"], root, 60)
    merged = _now()
    fields = {"applied_at": merged.isoformat(), "merged_at": merged.isoformat(), "pr_url": pr_url,
              "merge_sha": sha.strip().splitlines()[-1].strip() if sha.strip() else "",
              "apply_error": None, "applied_by": applied_by, **extra, **_baseline(row, merged)}
    led.set_state(row["id"], "applied", **fields)
    return {"ok": True, "id": row["id"], "state": "applied", "pr_url": pr_url,
            "merge_sha": fields["merge_sha"], "baseline_rate": fields["baseline_rate"]}


def _apply_issue(led, row: dict) -> dict:
    root = source_repo()
    body = f"{row.get('issue_body')}\n\n{_trailers(row)}"
    rc, out = run(["gh", "issue", "create", "--title", row.get("issue_title") or row.get("title") or "",
                   "--body", body], root)
    url = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""
    if not url.startswith("http"):
        return _fail(led, row, f"gh issue create failed: {_tail(out)}")
    led.set_state(row["id"], "applied", applied_at=_now().isoformat(), issue_url=url, apply_error=None)
    return {"ok": True, "id": row["id"], "state": "applied", "issue_url": url}


def _open_row(led, pid: str) -> dict:
    row = led.find(pid)
    if row is None:
        raise Failure(f"proposal {pid} is not in the ledger")
    if row.get("state", "ready") not in led.OPEN_STATES:
        raise Failure(f"proposal {pid} is {row.get('state')}, not ready")
    return row


def cmd_apply(args) -> dict:
    led = _ledger()
    row = _open_row(led, args.id)
    insert_text = args.insert_text
    if args.insert_file:
        with open(args.insert_file, "r", encoding="utf-8") as fh:
            insert_text = fh.read()
    kind = row.get("kind")
    if kind == "issue":
        if insert_text is not None:
            raise Failure("an issue proposal has no text to edit")
        return _apply_issue(led, row)
    if kind == "rule_insert":
        return _apply_rule(led, row, insert_text, "auto" if args.auto else "review")
    raise Failure(f"a {kind} proposal applies through lib/apply-proposal.py, not /autoheal-review")


# ---------------------------------------------------------------------
# revert and redraft (#1099 Phase 4.1, 4.2).
# ---------------------------------------------------------------------

REVERTIBLE_STATES = ("applied", "measured")


def _merged_row(led, pid: str) -> dict:
    """The newest applied or measured row for an id."""
    rows = [r for r in led.read_rows() if r.get("id") == pid and r.get("state") in REVERTIBLE_STATES]
    if not rows:
        raise Failure(f"proposal {pid} has no applied or measured row to act on")
    row = rows[-1]
    if row.get("kind") != "rule_insert":
        raise Failure(f"proposal {pid} is a {row.get('kind')} fix with no commit to revert")
    return row


def _trailer_commit(root: str, row: dict) -> str:
    """The commit on origin/main that applied the row: its merge_sha when that is on
    origin/main, else the newest commit carrying `Autoheal-Id: <id>`."""
    sha = str(row.get("merge_sha") or "")
    if re.fullmatch(r"[0-9a-f]{7,40}", sha):
        rc, _ = run(["git", "-C", root, "merge-base", "--is-ancestor", sha, "origin/main"], root, 60)
        if rc == 0:
            return sha
    pid = re.escape(str(row["id"]))
    rc, out = run(["git", "-C", root, "log", "origin/main", "-1", "--format=%H",
                   f"--grep=^Autoheal-Id: {pid}$"], root, 60)
    found = out.strip()
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", found):
        raise Failure(f"no commit with Autoheal-Id: {row['id']} on origin/main")
    return found


def revert_row(led, row: dict, reason: str, by: str) -> dict:
    """Open, check, squash-merge and clean up a `git revert` PR for an applied fix,
    then mark the row reverted. On failure the row keeps its state and gets a
    revert_error (plus revert_pr_url once a PR exists, so a retry merges it)."""
    pid, state = row["id"], row.get("state")

    def failed(message: str, **fields) -> dict:
        led.set_state(pid, state, from_states=(state,), revert_error=message, **fields)
        out = {"ok": False, "id": pid, "state": state, "error": message}
        out.update(fields)
        return out

    try:
        root = source_repo()
    except Failure as exc:
        return failed(str(exc))
    rc, out = run(["git", "-C", root, "fetch", "origin", "main"], root)
    if rc != 0:
        return failed(f"fetch failed: {_tail(out)}")
    try:
        sha = _trailer_commit(root, row)
    except Failure as exc:
        return failed(str(exc))
    branch = f"autoheal/revert-{pid}"
    subject = f"#auto: revert autoheal proposal {pid}"
    body = f"This reverts commit {sha}.\n\n{reason}\n\nAutoheal-Revert: {pid}"
    pr_url = row.get("revert_pr_url")
    if not pr_url:
        def prepare(wt: str) -> None:
            rc, out = run(["git", "revert", "--no-commit", sha], wt)
            if rc != 0:
                raise Failure(f"revert_conflict: {_tail(out)}")

        try:
            pr_url, _ = _open_pr(root, branch, prepare, subject, body)
        except Failure as exc:
            return failed(str(exc))
    try:
        _wait_for_checks(pr_url, root)
        _merge(pr_url, root, subject, body)
    except Failure as exc:
        return failed(str(exc), revert_pr_url=pr_url)
    _delete_remote_branch(root, branch)
    _, merged = run(["gh", "pr", "view", pr_url, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"], root, 60)
    fields = {"reverted_at": _now().isoformat(), "reverted_by": by, "revert_reason": reason,
              "revert_pr_url": pr_url, "reverted_commit": sha, "revert_error": None,
              "revert_merge_sha": merged.strip().splitlines()[-1].strip() if merged.strip() else ""}
    led.set_state(pid, "reverted", from_states=(state,), **fields)
    return {"ok": True, "id": pid, "state": "reverted", "revert_pr_url": pr_url, "reverted_commit": sha}


def cmd_revert(args) -> dict:
    led = _ledger()
    row = _merged_row(led, args.id)
    reason = args.reason or "Reverted by the user through /autoheal-review."
    return revert_row(led, row, reason, "auto" if args.auto else "review")


def cmd_redraft(args) -> dict:
    """Stop a measured fix covering its signature, so the next nightly run drafts the
    signature again from the newer samples. The merged rule stays in place."""
    led = _ledger()
    row = _merged_row(led, args.id)
    if row.get("state") != "measured":
        raise Failure(f"proposal {args.id} has not been measured yet; redraft is offered after the 14-day check")
    now = _now().isoformat()
    led.set_state(args.id, "measured", from_states=("measured",), redraft_requested_at=now)
    return {"ok": True, "id": args.id, "state": "measured", "redraft_requested_at": now}


def cmd_reject(args) -> dict:
    led = _ledger()
    _open_row(led, args.id)
    now = _now()
    until = (now + dt.timedelta(days=REJECT_DAYS)).isoformat()
    led.set_state(args.id, "rejected", rejected_at=now.isoformat(), reject_reason=args.reason,
                  suppressed_until=until)
    return {"ok": True, "id": args.id, "state": "rejected", "suppressed_until": until}


def cmd_snooze(args) -> dict:
    led = _ledger()
    _open_row(led, args.id)
    until = (_now() + dt.timedelta(days=args.days)).isoformat()
    led.set_state(args.id, "snoozed", snoozed_until=until)
    return {"ok": True, "id": args.id, "state": "snoozed", "snoozed_until": until}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--limit", type=int, default=LIST_LIMIT)
    p.add_argument("--id", default="")
    p.add_argument("--now", default="")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("apply")
    p.add_argument("id")
    p.add_argument("--insert-file", default="")
    p.add_argument("--insert-text", default=None)
    p.add_argument("--auto", action="store_true", help="record applied_by auto (the auto-apply step)")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("revert")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p.add_argument("--auto", action="store_true", help="record reverted_by auto (the auto-apply step)")
    p.set_defaults(fn=cmd_revert)
    p = sub.add_parser("redraft")
    p.add_argument("id")
    p.set_defaults(fn=cmd_redraft)
    p = sub.add_parser("reject")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_reject)
    p = sub.add_parser("snooze")
    p.add_argument("id")
    p.add_argument("--days", type=int, default=SNOOZE_DAYS)
    p.set_defaults(fn=cmd_snooze)
    args = ap.parse_args(argv)
    try:
        result = args.fn(args)
    except Failure as exc:
        result = {"ok": False, "id": getattr(args, "id", ""), "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
