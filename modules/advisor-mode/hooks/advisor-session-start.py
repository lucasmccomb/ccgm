#!/usr/bin/env python3
"""
SessionStart hook: put THIS session into advisor mode, and clean up flags left
behind by sessions that are gone.

Advisor-mode state is one flag file per session,
`~/.claude/advisor-mode/<session_id>`, so one session's mode never binds
another's. This hook owns three jobs, in order:

  1. Migration — the mode used to be a single regular file at
     `~/.claude/advisor-mode`. If that file is still there, delete it; the
     path becomes the state directory.
  2. Garbage collection — a session that crashed never ran SessionEnd, so its
     flag would sit there forever. A flag whose session has no transcript
     under `~/.claude/projects/*/<session_id>.jsonl` is removed once it is
     more than an hour old (the grace period keeps a session that started
     seconds ago, and has not written its transcript yet, from being swept).
     A flag whose transcript has not been touched in three days is removed
     too. The current session's flag is never touched.
  3. Auto-on — create this session's flag, so every session starts in advisor
     mode. Opt out with CCGM_ADVISOR_AUTO=false in the environment or in
     `~/.claude/.ccgm.env` (environment wins; unset means on), matching
     CCGM_AUTO_UPDATE_CHECK / CCGM_RULE_ENFORCEMENT. GC still runs when the
     auto-on is opted out.

`source == "compact"` skips the auto-on: compaction is mid-session continuity,
and re-creating the flag there would silently undo an explicit `/advisor off`.
An existing flag is never rewritten, so a resume keeps its original timestamp.

Never raises, never writes to stdout (the per-turn posture injection is
advisor-posture.py's job), always exits 0.
"""

import glob
import json
import os
import re
import sys
import time

SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"
AUTO_ENV = "CCGM_ADVISOR_AUTO"
FALSE_VALUES = ("false", "0", "no", "off")

# Session ids are uuids; anything else cannot name a flag file. Rejecting
# separators and dot-entries keeps the flag inside the state directory.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")

NO_TRANSCRIPT_GRACE_SECONDS = 60 * 60          # 1 hour
STALE_TRANSCRIPT_SECONDS = 3 * 24 * 60 * 60    # 3 days


def home():
    return os.path.expanduser("~")


def state_dir():
    return os.path.join(home(), ".claude", "advisor-mode")


def session_id(data):
    """This session's id: hook input first, environment as fallback."""
    for candidate in (data.get("session_id"), os.environ.get(SESSION_ID_ENV)):
        if not isinstance(candidate, str):
            continue
        candidate = candidate.strip()
        if candidate in (".", "..") or not SESSION_ID_RE.fullmatch(candidate):
            continue
        return candidate
    return None


def auto_on_enabled():
    """CCGM_ADVISOR_AUTO: environment wins over .ccgm.env; unset means on."""
    value = os.environ.get(AUTO_ENV)
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in FALSE_VALUES
    env_file = os.path.join(home(), ".claude", ".ccgm.env")
    try:
        with open(env_file) as handle:
            for line in handle:
                line = line.strip()
                if line.startswith(AUTO_ENV + "="):
                    setting = line.split("=", 1)[1].strip().strip("'\"").lower()
                    return setting not in FALSE_VALUES
    except (OSError, IOError):
        pass
    return True


def migrate_legacy_file(directory):
    """The pre-per-session state was a regular file at this exact path."""
    try:
        if os.path.isfile(directory) and not os.path.islink(directory):
            os.remove(directory)
    except OSError:
        pass


def collect_garbage(directory, current_sid):
    """Drop flags whose session is gone. Never touches the current session."""
    now = time.time()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name == current_sid:
            continue
        flag = os.path.join(directory, name)
        try:
            if not os.path.isfile(flag):
                continue
            transcripts = glob.glob(os.path.join(
                home(), ".claude", "projects", "*", name + ".jsonl"))
            if not transcripts:
                # A session that just started may not have a transcript yet.
                if now - os.path.getmtime(flag) > NO_TRANSCRIPT_GRACE_SECONDS:
                    os.remove(flag)
                continue
            newest = max(os.path.getmtime(t) for t in transcripts)
            if now - newest > STALE_TRANSCRIPT_SECONDS:
                os.remove(flag)
        except OSError:
            continue  # a racing writer or an unreadable entry: leave it


def enable(directory, sid):
    """Create this session's flag. An existing flag keeps its timestamp."""
    flag = os.path.join(directory, sid)
    if os.path.exists(flag):
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(flag, "w") as handle:
            handle.write("on %s\n" % stamp)
    except (OSError, IOError):
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    directory = state_dir()
    migrate_legacy_file(directory)
    try:
        os.makedirs(directory)
    except OSError:
        pass  # already there, or it cannot be created — nothing else to do

    sid = session_id(data)
    collect_garbage(directory, sid)

    if not sid:
        return
    if data.get("source") == "compact":
        return
    if not auto_on_enabled():
        return
    enable(directory, sid)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a session must never fail to start because of this hook
    sys.exit(0)
