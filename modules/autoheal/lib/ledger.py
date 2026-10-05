#!/usr/bin/env python3
"""ledger.py - the single autoheal proposal ledger (#1099 Phase 3.1).

All proposals live in one JSONL file, ~/.claude/autoheal/proposals.jsonl
(override: CCGM_AUTOHEAL_LEDGER, or CCGM_AUTOHEAL_DIR for the directory).
One row per proposal, with a `state`:

  ready      shown to the user, waiting for a decision
  applied    merged (or applied locally) by /autoheal-apply
  rejected   the user said no
  snoozed    deferred until `snoozed_until`
  dropped    drafted, then failed the validation gate; feeds the redraft cooldown
  skipped    the model declined to draft; the signature stays covered
  measured   applied, and the +14 day outcome is recorded (`outcome`: effective,
             ineffective, harmful or unmeasurable)
  reverted   applied (or measured), then undone by a merged revert PR
  legacy     written before the redesign; never shown

Lookup by id covers the whole ledger. Rows with a `signature_id` also feed the
aggregator's coverage and cooldown logic. Retention never deletes `ready` rows.

CLI (used by the bash scripts):
  ledger.py day <YYYY-MM-DD>    print that day's rows (any state) as JSONL
  ledger.py ready               print rows waiting for a decision as JSONL
  ledger.py prune <days>        drop `dropped` rows older than <days>; prints the count
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import sys
import tempfile

STATES = ("ready", "applied", "rejected", "snoozed", "dropped", "skipped",
          "measured", "reverted", "legacy")
# States a row passes through while a person can still act on it.
OPEN_STATES = ("ready", "snoozed")


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def ledger_path() -> str:
    return os.environ.get("CCGM_AUTOHEAL_LEDGER") or os.path.join(autoheal_dir(), "proposals.jsonl")


def read_rows(path: str | None = None) -> list:
    """Every parseable row, in file order. A missing file is an empty ledger."""
    rows = []
    try:
        with open(path or ledger_path(), "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def append_row(row: dict, path: str | None = None) -> None:
    """Locked append, safe across clones writing at once."""
    path = path or ledger_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def find(proposal_id: str, path: str | None = None):
    """The row for an id: the newest open row, else the newest row. None if absent.

    A signature can have several rows (dropped drafts, then a ready one), all
    with the same id, so a plain "last match" is not enough.
    """
    matches = [r for r in read_rows(path) if r.get("id") == proposal_id]
    open_rows = [r for r in matches if r.get("state", "ready") in OPEN_STATES]
    return (open_rows or matches or [None])[-1]


def _rewrite(path: str, mutate, skip=None) -> bool:
    """Run mutate(rows) -> bool under the ledger lock and write the result atomically."""
    if not os.path.exists(path):
        return False
    lock_fd = os.open(path + ".lock", os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Keep unparseable lines as they are; only parsed rows are offered to mutate.
        lines = []
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except ValueError:
                    row = None
                lines.append(row if isinstance(row, dict) else raw)
        rows = [item for item in lines if isinstance(item, dict)]
        if not mutate(rows):
            return False
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".proposals.")
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            for item in lines:
                if skip and skip(item):
                    continue
                out.write(item if isinstance(item, str)
                          else json.dumps(item, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        return True
    finally:
        os.close(lock_fd)


def set_state(proposal_id: str, state: str, path: str | None = None,
              from_states: tuple = OPEN_STATES, **fields) -> bool:
    """Move the newest row for an id whose state is in `from_states` (default: the
    open states) to `state`, adding `fields`. False if there is none.

    Outcome measurement moves `applied` rows to `measured`, and a revert moves
    `applied` or `measured` rows to `reverted`, so those callers pass `from_states`.
    """
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    path = path or ledger_path()

    def mutate(rows):
        for row in reversed(rows):
            if row.get("id") == proposal_id and row.get("state", "ready") in from_states:
                row["state"] = state
                row.update(fields)
                return True
        return False

    return _rewrite(path, mutate)


def row_day(row: dict) -> str:
    """The day a row was drafted for: source_day, else the date of generated_at."""
    day = row.get("source_day")
    if isinstance(day, str) and day:
        return day[:10]
    stamp = row.get("generated_at")
    return stamp[:10] if isinstance(stamp, str) else ""


def rows_for_day(day: str, path: str | None = None) -> list:
    return [r for r in read_rows(path) if row_day(r) == day]


def ready_rows(now: dt.datetime | None = None, path: str | None = None) -> list:
    """Rows waiting for a decision: ready, plus snoozed rows whose snooze has ended."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for row in read_rows(path):
        state = row.get("state", "ready")
        if state == "snoozed":
            try:
                until = dt.datetime.fromisoformat(str(row.get("snoozed_until")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if until.tzinfo is None:
                until = until.replace(tzinfo=dt.timezone.utc)
            if until <= now:
                out.append(row)
        elif state == "ready":
            out.append(row)
    return out


def prune_dropped(days: int, now: dt.datetime | None = None, path: str | None = None) -> int:
    """Delete `dropped` rows older than `days`. Every other state is kept.

    Applied, rejected, skipped and legacy rows keep a signature covered, and a
    ready or snoozed row is work nobody has finished, so none of them expire.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=days)).date().isoformat()
    path = path or ledger_path()
    removed = []

    def mutate(rows):
        removed.extend(r for r in rows
                       if r.get("state") == "dropped" and row_day(r) and row_day(r) < cutoff)
        for r in removed:
            r["_pruned"] = True
        return bool(removed)

    if not _rewrite(path, mutate, skip=lambda item: isinstance(item, dict) and item.get("_pruned")):
        return 0
    return len(removed)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "day":
        for row in rows_for_day(args[1]):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args == ["ready"]:
        for row in ready_rows():
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if len(args) == 2 and args[0] == "prune" and args[1].isdigit():
        print(prune_dropped(int(args[1])))
        return 0
    sys.stderr.write("usage: ledger.py day <YYYY-MM-DD> | ready | prune <days>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
