#!/usr/bin/env python3
"""SessionStart hook: tell the user about ready autoheal fixes and a dead job.

Prints one line (systemMessage, shown to the user) plus a short additionalContext
for the model, at most once per UTC day per machine. Silent when there is nothing
to say. No network. It never blocks a session: any error prints nothing, exit 0.
It never asks a question; the notice is plain text.

Says something when:
  - the ledger (~/.claude/autoheal/proposals.jsonl) has ready rows
        autoheal: 2 fixes ready (zsh quoting in Bash, cp -i alias) — run /autoheal-review
  - health.json is older than 26h, or its status is failed
        autoheal: last good run 3d ago (<reason>) — /autoheal doctor
  - auto-apply applied a fix (#1099 Phase 4.2), announced once
        autoheal: applied 1 fix: <title> (undo: /autoheal-review revert <id>)
  - a fix measured at +14 days was harmful or ineffective, or auto-apply
    reverted a harmful one (#1099 Phase 4.1), each announced once
        autoheal: <title> looks harmful (2.0 → 3.0 per 100 calls) — /autoheal-review revert <id>
        autoheal: <title> is ineffective (2.0 → 1.5 per 100 calls) — /autoheal-review revert <id> or /autoheal-review redraft <id>
        autoheal: reverted <title> (failures rose 2.0 → 3.0 per 100 calls)
  - the launchd job runs a file that does not exist (checked once a day, cached)
        autoheal: scheduled job runs <path>, which does not exist — /autoheal doctor
        autoheal: job points outside your home: <path> — /autoheal doctor

Says nothing when health.json is absent or its status is paused, when the cwd is
a subagent worktree (the day's notice is kept for a real session), or when
~/.claude/autoheal does not exist.

State files, in the autoheal dir: notice-sentinel (the date of the last notice),
notice-launchd.json (the day's launchctl result), notice-announced.json (keys of
the applied fixes and outcomes already announced).

Env: CCGM_AUTOHEAL_DIR (default ~/.claude/autoheal). Tests only:
CCGM_AUTOHEAL_NOW (ISO time), CCGM_AUTOHEAL_REAL_HOME,
CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR.
"""
from __future__ import annotations

import glob
import json
import os
import pwd
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

STALE_HOURS = 26
MAX_NAMES = 3
MAX_ANNOUNCED = 500
SYSTEM_PREFIXES = ("/bin/", "/sbin/", "/usr/", "/opt/homebrew/", "/System/", "/Library/", "/Applications/")


def _dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def _real_home() -> str:
    return os.environ.get("CCGM_AUTOHEAL_REAL_HOME") or pwd.getpwuid(os.getuid()).pw_dir


def _parse(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _ready_names(root: str, now: datetime) -> list:
    names = []
    try:
        fh = open(os.path.join(root, "proposals.jsonl"), encoding="utf-8")
    except OSError:
        return names
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            state = row.get("state", "ready")
            if state == "snoozed":
                until = _parse(row.get("snoozed_until"))
                state = "ready" if until is not None and until <= now else state
            if state == "ready":
                title = row.get("title") if isinstance(row.get("title"), str) else ""
                names.append(title.split(": ")[0].strip() or str(row.get("id", "fix")))
    return list(dict.fromkeys(names))


def _rows(root: str) -> list:
    rows = []
    try:
        fh = open(os.path.join(root, "proposals.jsonl"), encoding="utf-8")
    except OSError:
        return rows
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _change(row: dict) -> str:
    """'2.0 → 3.0 per 100 calls', or the occurrence counts when no rate exists."""
    base, post = _num(row.get("baseline_rate")), _num(row.get("post_rate"))
    if row.get("outcome_basis", "rate") == "rate" and base is not None and post is not None:
        return f"{base:.1f} → {post:.1f} per 100 calls"
    return f"{row.get('baseline_occurrences')} → {row.get('post_occurrences')} failures in 14 days"


def _harm_detail(row: dict) -> str:
    base, post = _num(row.get("baseline_rate")), _num(row.get("post_rate"))
    new = [s for s in (row.get("new_signatures") or []) if isinstance(s, str)]
    rose = base is not None and post is not None and post > base
    if new and not rose:
        return "new failures: " + ", ".join(new[:2])
    return _change(row)


def _outcome_items(rows: list) -> tuple:
    """(auto-applied items, outcome items), each a list of (announce key, text)."""
    applied, outcomes = [], []
    for row in rows:
        pid = str(row.get("id") or "")
        title = row.get("title") if isinstance(row.get("title"), str) and row.get("title") else pid
        state = row.get("state")
        if state == "applied" and row.get("applied_by") == "auto":
            applied.append((f"applied:{pid}:{row.get('merged_at')}",
                            f"{title} (undo: /autoheal-review revert {pid})"))
        elif state == "reverted" and row.get("reverted_by") == "auto":
            detail = _harm_detail(row)
            detail = f"failures rose {detail}" if not detail.startswith("new failures") else detail
            outcomes.append((f"reverted:{pid}:{row.get('reverted_at')}", f"reverted {title} ({detail})"))
        elif state == "measured" and row.get("outcome") == "harmful":
            outcomes.append((f"measured:{pid}:{row.get('measured_at')}",
                             f"{title} looks harmful ({_harm_detail(row)}) — /autoheal-review revert {pid}"))
        elif state == "measured" and row.get("outcome") == "ineffective":
            outcomes.append((f"measured:{pid}:{row.get('measured_at')}",
                             f"{title} is ineffective ({_change(row)}) — /autoheal-review revert {pid} "
                             f"or /autoheal-review redraft {pid}"))
    return applied, outcomes


def _applied_part(items: list) -> str:
    noun = "fix" if len(items) == 1 else "fixes"
    return f"applied {len(items)} {noun}: " + ", ".join(text for _, text in items)


def _fixes_part(names: list) -> str:
    shown = ", ".join(names[:MAX_NAMES]) + (f", +{len(names) - MAX_NAMES} more" if len(names) > MAX_NAMES else "")
    noun = "fix" if len(names) == 1 else "fixes"
    return f"{len(names)} {noun} ready ({shown}) — run /autoheal-review"


def _ago(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours // 24}d ago" if hours >= 24 else f"{hours}h ago"


def _health_part(root: str, now: datetime):
    health = _load_json(os.path.join(root, "health.json"))
    if not isinstance(health, dict):
        return None
    status = str(health.get("status", "")).lower()
    if status == "paused":
        return None
    limit = timedelta(hours=STALE_HOURS)
    generated = _parse(health.get("generated_at"))
    last_ok = _parse(health.get("last_success_at"))
    stale = generated is None or now - generated > limit or (last_ok is not None and now - last_ok > limit)
    failed = status in ("failed", "red")
    if not (stale or failed):
        return None
    reasons = [r for r in (health.get("reasons") or []) if isinstance(r, dict) and r.get("message")]
    if reasons:
        reason = " ".join(str(reasons[0]["message"]).split())[:80]
    else:
        reason = "status failed" if failed else f"no run in the last {STALE_HOURS}h"
    when = f"last good run {_ago(now - last_ok)}" if last_ok else "no good run recorded"
    return f"{when} ({reason}) — /autoheal doctor"


def _program_paths(printed: str) -> list:
    """Absolute paths in launchctl's `program` and `arguments` that the job needs."""
    entries, in_args = [], False
    for raw in printed.splitlines():
        line = raw.strip()
        if in_args:
            if line.startswith("}"):
                in_args = False
            elif line:
                entries.append(line)
        elif line.startswith("program ="):
            entries.append(line.split("=", 1)[1].strip())
        elif line.startswith("arguments = {"):
            in_args = True
    home = _real_home()
    paths = []
    for entry in entries:
        try:
            tokens = shlex.split(entry)
        except ValueError:
            tokens = entry.split()
        for token in tokens:
            token = token.replace("${HOME}", home).replace("$HOME", home)
            if token.startswith("~/"):
                token = home + token[1:]
            if token.startswith("/") and not token.startswith(SYSTEM_PREFIXES) and "$" not in token:
                paths.append(token)
    return list(dict.fromkeys(paths))


def _launchd_problem(label: str):
    try:
        res = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                             capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return f"scheduled job {label} is not loaded — /autoheal doctor"
    paths = _program_paths(res.stdout)
    for path in paths:
        if not os.path.exists(path):
            return f"scheduled job runs {path}, which does not exist — /autoheal doctor"
    home = os.path.realpath(_real_home())
    for path in paths:
        real = os.path.realpath(path)
        if real != home and not real.startswith(home + os.sep):
            return f"job points outside your home: {path} — /autoheal doctor"
    return None


def _launchd_part(root: str, today: str):
    if not shutil.which("launchctl"):
        return None
    agents = os.environ.get("CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR") or os.path.join(_real_home(), "Library", "LaunchAgents")
    plists = sorted(glob.glob(os.path.join(agents, "com.*.ccgm.autoheal.daily.plist")))
    if not plists:
        return None
    cache_path = os.path.join(root, "notice-launchd.json")
    cached = _load_json(cache_path)
    if isinstance(cached, dict) and cached.get("date") == today:
        return cached.get("problem")
    label = os.path.basename(plists[0])[: -len(".plist")]
    problem = _launchd_problem(label)
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump({"date": today, "problem": problem}, fh)
    except OSError:
        pass
    return problem


def build_notice(root: str, now: datetime):
    """(user line, model context) or None when there is nothing to say today."""
    today = now.date().isoformat()
    try:
        with open(os.path.join(root, "notice-sentinel"), encoding="utf-8") as fh:
            if fh.read().strip() == today:
                return None
    except OSError:
        pass
    names = _ready_names(root, now)
    parts = []
    if names:
        parts.append(_fixes_part(names))
    announced_path = os.path.join(root, "notice-announced.json")
    announced = _load_json(announced_path)
    announced = [k for k in announced if isinstance(k, str)] if isinstance(announced, list) else []
    applied, outcomes = _outcome_items(_rows(root))
    applied = [item for item in applied if item[0] not in announced]
    outcomes = [item for item in outcomes if item[0] not in announced]
    if applied:
        parts.append(_applied_part(applied))
    parts += [text for _, text in outcomes]
    for part in (_health_part(root, now), _launchd_part(root, today)):
        if part:
            parts.append(part)
    if not parts:
        return None
    with open(os.path.join(root, "notice-sentinel"), "w", encoding="utf-8") as fh:
        fh.write(today + "\n")
    new_keys = [key for key, _ in applied + outcomes]
    if new_keys:
        with open(announced_path, "w", encoding="utf-8") as fh:
            json.dump((announced + new_keys)[-MAX_ANNOUNCED:], fh)
    line = "autoheal: " + " | ".join(parts)
    context = (line + ". The user has seen this one line. If they ask about autoheal, point them to the "
               "command it names. Do not apply fixes or raise this unprompted.")
    return line, context


def main() -> int:
    try:
        try:
            cwd = json.load(sys.stdin).get("cwd") or os.getcwd()
        except (ValueError, AttributeError):
            cwd = os.getcwd()
        root = _dir()
        if "/.claude/worktrees/" in str(cwd).rstrip("/") + "/" or not os.path.isdir(root):
            return 0
        now = _parse(os.environ.get("CCGM_AUTOHEAL_NOW")) or datetime.now(timezone.utc)
        notice = build_notice(root, now)
        if notice:
            json.dump({"systemMessage": notice[0],
                       "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": notice[1]}},
                      sys.stdout)
    except Exception:  # noqa: BLE001 -- a notice must never block a session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
