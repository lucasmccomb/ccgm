#!/usr/bin/env python3
"""autoheal-aggregate.py - deterministic friction signature aggregator.

Counts recurring tool failures with plain code (no model, no network) so the
drafting step only sees signatures that earned attention (#1099 Phase 2.1).

Input, under the autoheal data dir ($CCGM_AUTOHEAL_DIR, default
~/.claude/autoheal):
  events/{date}.jsonl   tool_failure and user_interrupt rows
  counts/{date}.json    per-tool call counters ({"Bash": 123, ...})
  proposals.jsonl       the proposal ledger (lib/ledger.py); rows carrying
                        `signature_id` cover that signature unless their state
                        is "dropped"

A dropped row covers its signature for a cooldown instead (item `excluded`:
"cooldown", with `cooldown_until`), so a draft that cannot pass validation is
not paid for again every night:
  - content drop (personal_data, module_tests, apply_conflict, rule_budget,
    anchor_missing, path_not_candidate, insert_too_long, ...): `redraft_cooldown_days`
    (default 14) from the row's drop date. Each further content drop doubles
    it, capped at 90 days.
  - validation_unavailable (infrastructure, not the proposal's fault): 1 day.
    Three such drops in a row start the 14-day cooldown.
A model `skip` row is not dropped: it covers its signature with no expiry.
A `rejected` row covers its signature until its `suppressed_until` (90 days after
/autoheal-review rejected it); a `snoozed` row covers it while the row exists.

Signature: (tool_name, cmd_head, error_class), from tool_failure rows only.
Rows written before PR #1112 have no error_class; they become class
"unknown" and never qualify. user_interrupt rows are tallied per tool in a
separate `interrupts` list.

Output: signatures/{date}.json, ranked by count x sessions.

Bar and window come from config.json (CCGM_AUTOHEAL_CONFIG or
<dir>/config.json), key "aggregation":
  {"window_days": 14, "min_occurrences": 5, "min_sessions": 2, "min_days": 2,
   "redraft_cooldown_days": 14}

Outcome measurement (#1099 Phase 4.1). Each run also measures every `applied`
rule_insert row whose 14-day post-merge window has ended (the window is the 14
days after the merge day, so a row is due on merge day + 15). post_rate is
signature_rate() over that window; it is compared with the row's baseline_rate
(the 14 days before the merge, written by /autoheal-review):
  effective     post_rate <= 50% of baseline_rate
  ineffective   above 50% and at most 100%
  harmful       above baseline_rate, or a new signature (same tool and
                non-empty cmd_head, another error_class, at least
                NEW_SIGNATURE_MIN_OCCURRENCES failures in the post window and
                none in the baseline window) appeared
  unmeasurable  no baseline to compare against
When either window has no counted calls, failure counts over the two equal
windows are compared instead of rates. The row becomes `measured` with the
outcome. Reverting a harmful fix is the auto-apply step's job, not this one's:
the aggregator makes no git, gh or network call.

Usage: autoheal-aggregate.py [--date YYYY-MM-DD]   (default: today, UTC)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

DEFAULTS = {"window_days": 14, "min_occurrences": 5, "min_sessions": 2, "min_days": 2,
            "redraft_cooldown_days": 14}
OUTCOME_WINDOW_DAYS = 14
EFFECTIVE_MAX_RATIO = 0.5
NEW_SIGNATURE_MIN_OCCURRENCES = 2
MAX_COOLDOWN_DAYS = 90
INFRA_DROP_REASONS = ("validation_unavailable",)
INFRA_STREAK_FOR_COOLDOWN = 3
MAX_SAMPLES = 3
MAX_SAMPLE_LEN = 300
UNKNOWN = "unknown"
KINDS = ("tool_failure", "user_interrupt")


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def _redactor():
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(here, "..", "..", "hooks", "lib"),
        os.path.expanduser("~/.claude/lib"),
    ):
        if os.path.isfile(os.path.join(path, "hook_utils.py")):
            sys.path.insert(0, path)
            try:
                from hook_utils import redact_secrets

                return redact_secrets
            except Exception:
                pass
            finally:
                sys.path.remove(path)
    return lambda text: text


def load_config(data_dir: str) -> dict:
    path = os.environ.get("CCGM_AUTOHEAL_CONFIG") or os.path.join(data_dir, "config.json")
    cfg = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return cfg
    agg = raw.get("aggregation") if isinstance(raw, dict) else None
    if isinstance(agg, dict):
        for key in DEFAULTS:
            val = agg.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                cfg[key] = val
    return cfg


def signature_id(sig: tuple) -> str:
    return hashlib.sha256("\x1f".join(sig).encode("utf-8")).hexdigest()[:12]


def _dates(start: dt.date, end: dt.date):
    for n in range((end - start).days + 1):
        yield start + dt.timedelta(days=n)


def _read_rows(data_dir: str, date: dt.date):
    path = os.path.join(data_dir, "events", date.isoformat() + ".jsonl")
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _read_counts(data_dir: str, date: dt.date) -> dict:
    try:
        with open(os.path.join(data_dir, "counts", date.isoformat() + ".json"), "r",
                  encoding="utf-8") as fh:
            val = json.load(fh)
    except (OSError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _calls(data_dir: str, tool: str, start: dt.date, end: dt.date) -> int:
    total = 0
    for d in _dates(start, end):
        n = _read_counts(data_dir, d).get(tool, 0)
        if isinstance(n, int) and not isinstance(n, bool):
            total += n
    return total


def _rate(occurrences: int, calls: int):
    return occurrences / calls * 100 if calls > 0 else None


def row_signature(row: dict) -> tuple:
    """(tool_name, cmd_head, error_class); blind legacy rows -> unknown."""
    tool = str(row.get("tool_name") or "")
    cls = row.get("error_class")
    if not isinstance(cls, str) or not cls or cls == UNKNOWN:
        return (tool, "", UNKNOWN)
    head = row.get("cmd_head")
    return (tool, head if isinstance(head, str) else "", cls)


def signature_rate(data_dir: str, sig: tuple, start: dt.date, end: dt.date) -> dict:
    """Failure rate of one signature over [start, end] (inclusive).

    Returns {"occurrences", "calls", "rate_per_100_calls"}; the rate is None
    when counts/ holds no calls of the tool in the window.
    """
    sig = tuple(sig)
    occurrences = 0
    for d in _dates(start, end):
        for row in _read_rows(data_dir, d):
            if row.get("kind") == "tool_failure" and row_signature(row) == sig:
                occurrences += 1
    calls = _calls(data_dir, sig[0], start, end)
    return {"occurrences": occurrences, "calls": calls,
            "rate_per_100_calls": _rate(occurrences, calls)}


def _repo(cwd) -> str:
    """Repo name from a cwd: the dir under code/, minus -repos/-workspaces."""
    if not isinstance(cwd, str) or not cwd:
        return ""
    parts = [p for p in cwd.split("/") if p]
    if "code" in parts and parts.index("code") + 1 < len(parts):
        name = parts[parts.index("code") + 1]
    else:
        name = parts[-1] if parts else ""
    for suffix in ("-repos", "-workspaces"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _ledger_rows(data_dir: str):
    """Every row of the proposal ledger that names a signature."""
    try:
        fh = open(os.path.join(data_dir, "proposals.jsonl"), "r", encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("signature_id"), str):
                yield row

def _suppression_over(row: dict, as_of: dt.date) -> bool:
    """True for a rejected row whose `suppressed_until` (set by /autoheal-review) has passed."""
    if row.get("state") != "rejected":
        return False
    try:
        until = dt.datetime.fromisoformat(str(row.get("suppressed_until")).replace("Z", "+00:00"))
    except ValueError:
        return False  # a rejection with no end date stays in force
    return as_of > until.date()


def _covered_ids(data_dir: str, as_of: dt.date) -> set:
    """Signatures a ledger row still covers. A measured row the user asked to
    redraft (`/autoheal-review redraft`) stops covering its signature, so the
    next run drafts it again from the newer samples."""
    return {row["signature_id"] for row in _ledger_rows(data_dir)
            if row.get("state") != "dropped" and not _suppression_over(row, as_of)
            and not (row.get("state") == "measured" and row.get("redraft_requested_at"))}


def drop_history(data_dir: str) -> dict:
    """{signature_id: [(drop date, drop_reason), ...]} oldest first, dropped rows only."""
    hist: dict = {}
    for row in _ledger_rows(data_dir):
        if row.get("state") != "dropped":
            continue
        when = None
        for key in ("generated_at", "source_day"):
            try:
                when = dt.datetime.fromisoformat(str(row.get(key))).date()
                break
            except ValueError:
                continue
        if when is None:
            continue
        hist.setdefault(row["signature_id"], []).append((when, str(row.get("drop_reason") or "")))
    for rows in hist.values():
        rows.sort()
    return hist


def unavailable_streak(history: list) -> int:
    """Length of the run of validation_unavailable drops at the end of the history."""
    n = 0
    for _, reason in reversed(history):
        if reason not in INFRA_DROP_REASONS:
            break
        n += 1
    return n


def cooldown_until(history: list, base_days: int):
    """First date a dropped signature may be drafted again, or None with no history."""
    if not history:
        return None
    last_day, last_reason = history[-1]
    if last_reason in INFRA_DROP_REASONS:
        days = base_days if unavailable_streak(history) >= INFRA_STREAK_FOR_COOLDOWN else 1
    else:
        content_drops = sum(1 for _, r in history if r not in INFRA_DROP_REASONS)
        days = min(MAX_COOLDOWN_DAYS, base_days * 2 ** (content_drops - 1))
    return last_day + dt.timedelta(days=days)


def aggregate(data_dir: str, end: dt.date, cfg: dict) -> dict:
    redact = _redactor()
    start = end - dt.timedelta(days=cfg["window_days"] - 1)
    stats: dict = {}
    interrupts: dict = {}
    for d in _dates(start, end):
        iso = d.isoformat()
        for row in _read_rows(data_dir, d):
            kind = row.get("kind")
            if kind not in KINDS:
                continue
            sess = row.get("session_id") or ""
            if kind == "user_interrupt":
                rec = interrupts.setdefault(str(row.get("tool_name") or ""),
                                            {"count": 0, "sessions": set(), "days": set()})
                rec["count"] += 1
                rec["sessions"].add(sess)
                rec["days"].add(iso)
                continue
            sig = row_signature(row)
            rec = stats.get(sig)
            if rec is None:
                rec = stats[sig] = {"count": 0, "sessions": set(), "repos": set(),
                                    "days": set(), "first": iso, "last": iso, "samples": {}}
            rec["count"] += 1
            rec["sessions"].add(sess)
            repo = _repo(row.get("cwd"))
            if repo:
                rec["repos"].add(repo)
            rec["days"].add(iso)
            rec["last"] = iso  # days iterate in order
            err = row.get("error")
            if isinstance(err, str) and err:
                text = redact(err)[:MAX_SAMPLE_LEN]
                rec["samples"].pop(text, None)  # keep the latest occurrence last
                rec["samples"][text] = True

    covered = _covered_ids(data_dir, end)
    drops = drop_history(data_dir)
    call_totals: dict = {}

    out = []
    for sig, rec in stats.items():
        sid = signature_id(sig)
        tool = sig[0]
        if tool not in call_totals:
            call_totals[tool] = _calls(data_dir, tool, start, end)
        calls = call_totals[tool]
        excluded = None
        if sig[2] == UNKNOWN:
            excluded = "unknown"
        elif sid in covered:
            excluded = "covered"
        until = cooldown_until(drops.get(sid, []), cfg["redraft_cooldown_days"])
        if excluded is None and until is not None and end < until:
            excluded = "cooldown"
        meets = (rec["count"] >= cfg["min_occurrences"]
                 and len(rec["sessions"]) >= cfg["min_sessions"]
                 and len(rec["days"]) >= cfg["min_days"])
        item = {
            "signature_id": sid,
            "tool_name": sig[0],
            "cmd_head": sig[1],
            "error_class": sig[2],
            "count": rec["count"],
            "sessions": len(rec["sessions"]),
            "repos": len(rec["repos"]),
            "days": len(rec["days"]),
            "first_seen": rec["first"],
            "last_seen": rec["last"],
            "calls": calls,
            "rate_per_100_calls": _rate(rec["count"], calls),
            "samples": list(rec["samples"])[-MAX_SAMPLES:],
            "qualifies": meets and excluded is None,
        }
        if excluded:
            item["excluded"] = excluded
        if excluded == "cooldown":
            item["cooldown_until"] = until.isoformat()
        out.append(item)
    out.sort(key=lambda s: (-s["count"] * s["sessions"], s["signature_id"]))

    ints = [{"tool_name": t, "count": r["count"], "sessions": len(r["sessions"]),
             "days": len(r["days"])} for t, r in sorted(interrupts.items())]
    return {
        "date": end.isoformat(),
        "window_start": start.isoformat(),
        "window_days": cfg["window_days"],
        "bar": {k: cfg[k] for k in ("min_occurrences", "min_sessions", "min_days")},
        "signatures": out,
        "interrupts": ints,
    }


def _ledger_lib():
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("autoheal_ledger", os.path.join(here, "..", "lib", "ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _signatures_in(data_dir: str, tool: str, head: str, start: dt.date, end: dt.date) -> dict:
    """{signature: count} of tool_failure rows with this tool and cmd_head."""
    counts: dict = {}
    for d in _dates(start, end):
        for row in _read_rows(data_dir, d):
            if row.get("kind") != "tool_failure":
                continue
            sig = row_signature(row)
            if sig[0] == tool and sig[1] == head and sig[2] != UNKNOWN:
                counts[sig] = counts.get(sig, 0) + 1
    return counts


def classify(baseline, post) -> str:
    """effective | ineffective | harmful | unmeasurable, from two comparable numbers."""
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or baseline <= 0 or post is None:
        return "unmeasurable"
    if post <= baseline * EFFECTIVE_MAX_RATIO:
        return "effective"
    if post <= baseline:
        return "ineffective"
    return "harmful"


def _merge_day(row: dict):
    try:
        return dt.datetime.fromisoformat(str(row.get("merged_at")).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def measure_row(data_dir: str, row: dict, merged: dt.date) -> dict:
    """The outcome fields for one due applied row. Reads events and counts only."""
    start, end = merged + dt.timedelta(days=1), merged + dt.timedelta(days=OUTCOME_WINDOW_DAYS)
    sig = (str(row.get("tool_name") or ""), str(row.get("cmd_head") or ""), str(row.get("error_class") or ""))
    post = signature_rate(data_dir, sig, start, end)
    baseline_rate = row.get("baseline_rate")
    if isinstance(baseline_rate, (int, float)) and post["rate_per_100_calls"] is not None:
        outcome, basis = classify(baseline_rate, post["rate_per_100_calls"]), "rate"
    else:
        outcome, basis = classify(row.get("baseline_occurrences"), post["occurrences"]), "occurrences"
    new_sigs = []
    if sig[1]:
        before = _signatures_in(data_dir, sig[0], sig[1], merged - dt.timedelta(days=OUTCOME_WINDOW_DAYS), merged)
        after = _signatures_in(data_dir, sig[0], sig[1], start, end)
        new_sigs = sorted("|".join(s) for s, n in after.items()
                          if s != sig and s not in before and n >= NEW_SIGNATURE_MIN_OCCURRENCES)
    if new_sigs and outcome != "unmeasurable":
        outcome = "harmful"
    return {"outcome": outcome, "outcome_basis": basis,
            "post_rate": post["rate_per_100_calls"], "post_occurrences": post["occurrences"],
            "post_calls": post["calls"], "post_window": [start.isoformat(), end.isoformat()],
            "new_signatures": new_sigs}


def measure_outcomes(data_dir: str, today: dt.date) -> list:
    """Move every due applied rule_insert row to `measured`; returns [(id, outcome)]."""
    ledger = _ledger_lib()
    path = os.path.join(data_dir, "proposals.jsonl")
    done = []
    for row in ledger.read_rows(path):
        if row.get("state") != "applied" or row.get("kind") != "rule_insert":
            continue
        merged = _merge_day(row)
        if merged is None or today < merged + dt.timedelta(days=OUTCOME_WINDOW_DAYS + 1):
            continue
        fields = measure_row(data_dir, row, merged)
        if ledger.set_state(row["id"], "measured", path=path, from_states=("applied",),
                            measured_at=today.isoformat(), **fields):
            done.append((row["id"], fields["outcome"]))
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="window end, YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args(argv)
    try:
        end = (dt.date.fromisoformat(args.date) if args.date
               else dt.datetime.now(dt.timezone.utc).date())
    except ValueError:
        print("autoheal-aggregate: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    data_dir = autoheal_dir()
    result = aggregate(data_dir, end, load_config(data_dir))
    out_dir = os.path.join(data_dir, "signatures")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, end.isoformat() + ".json")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, out_path)
    qualifying = sum(1 for s in result["signatures"] if s["qualifies"])
    print(f"autoheal-aggregate: {len(result['signatures'])} signatures, "
          f"{qualifying} qualify -> {out_path}")
    measured = measure_outcomes(data_dir, end)
    if measured:
        detail = ", ".join(f"{pid} {outcome}" for pid, outcome in measured)
        print(f"autoheal-aggregate: measured {len(measured)} applied fix(es): {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
