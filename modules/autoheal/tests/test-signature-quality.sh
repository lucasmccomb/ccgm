#!/usr/bin/env bash
# Test suite for signature quality (#1137):
#   - lib/error_classes.py is the one classifier (class lookup, group flag).
#   - The harness worktree-isolation refusal gets its own class, and
#     refusal shapes do not fall through to "other".
#   - Classes flagged group_by_cmd_head=false collapse to (tool, "", class);
#     "other" and exit_code keep the per-cmd_head split.
#   - Stored rows are reclassified from their error text at aggregation time;
#     pre-#1112 rows with no error stay "unknown".
#   - "min_days" counts distinct days in the machine's local timezone, taken
#     from each row's timestamp, not the UTC event-file date.
# All fixtures are synthetic.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AGG="${MODULE_ROOT}/bin/autoheal-aggregate.py"
CLASSES_PY="${MODULE_ROOT}/lib/error_classes.py"
CLASSES_JSON="${MODULE_ROOT}/lib/error_classes.json"

TMP=$(mktemp -d -t autoheal_sigq.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT
export AGG TMP CLASSES_PY CLASSES_JSON

python3 - <<'PY'
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys

AGG = os.environ["AGG"]
BASE = os.environ["TMP"]
passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", msg)


END = dt.date(2026, 10, 4)

HARNESS = ("This agent is isolated in the worktree /work/tree but this command is too "
           "complex to verify that it stays inside the worktree. Refusing to run it - "
           "a worktree-isolated agent's git operations must target its own worktree. "
           "Split it into plain, separate commands and run them from /work/tree.")
HARNESS_EVAL = ("This agent is isolated in the worktree /work/tree but this command runs a "
                "string through eval, which can't be verified to stay inside the worktree. "
                "Refusing to run it - a worktree-isolated agent's git operations must "
                "target its own worktree.")

# ---- shared classifier ---------------------------------------------------
spec = importlib.util.spec_from_file_location("error_classes", os.environ["CLASSES_PY"])
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)
os.environ["CCGM_ERROR_CLASSES"] = os.environ["CLASSES_JSON"]
check(ec.classify(HARNESS) == "harness_worktree_isolation", "harness refusal classified")
check(ec.classify(HARNESS_EVAL) == "harness_worktree_isolation", "eval refusal classified")
check(ec.classify("Exit code 2\nboom") == "exit_code", "exit_code still classifies")
check(ec.classify("something odd") == "other", "unmatched text is other")
check(ec.groups_by_cmd_head("harness_worktree_isolation") is False, "harness class not split by cmd_head")
check(ec.groups_by_cmd_head("hook_denial_branch_guard") is False, "hook denial not split by cmd_head")
check(ec.groups_by_cmd_head("zsh_no_matches") is False, "zsh glob not split by cmd_head")
check(ec.groups_by_cmd_head("other") is True, "other keeps cmd_head")
check(ec.groups_by_cmd_head("exit_code") is True, "exit_code keeps cmd_head")
check(ec.groups_by_cmd_head("unknown") is True, "unknown class defaults to split")

# ---- aggregator fixtures -------------------------------------------------


def day(n):
    return (END - dt.timedelta(days=n)).isoformat()


def reset(name):
    d = os.path.join(BASE, name)
    os.environ["CCGM_AUTOHEAL_DIR"] = d
    os.environ["CCGM_AUTOHEAL_CONFIG"] = os.path.join(d, "config.json")
    os.makedirs(os.path.join(d, "events"), exist_ok=True)
    os.makedirs(os.path.join(d, "counts"), exist_ok=True)
    return d


def row(head, cls, err, sess="s1", ts=None, date=None):
    r = {"kind": "tool_failure", "session_id": sess, "tool_name": "Bash",
         "cwd": "/Users/x/code/proj", "cmd_head": head, "exit_code": 1}
    if err is not None:
        r["error"] = err
    if cls is not None:
        r["error_class"] = cls
    r["timestamp"] = ts or (date + "T12:00:00+00:00")
    return r


def write(d, date, rows):
    with open(os.path.join(d, "events", date + ".jsonl"), "a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def run(d, tz="UTC"):
    env = dict(os.environ, TZ=tz)
    p = subprocess.run([sys.executable, AGG, "--date", END.isoformat()],
                       capture_output=True, text=True, env=env)
    out = os.path.join(d, "signatures", END.isoformat() + ".json")
    return p, (json.load(open(out)) if os.path.isfile(out) else None)


# 3 cmd_heads x one harness refusal -> exactly 1 signature, sessions and days kept.
d = reset("harness")
for i, head in enumerate(["cat", "for", "sed"]):
    for n in range(4):
        write(d, day(1 + n % 2), [row(head, "other", HARNESS, sess="s%d" % (i + n % 2),
                                      date=day(1 + n % 2))])
p, data = run(d)
check(p.returncode == 0 and data is not None, "harness run ok: " + p.stderr)
sigs = data["signatures"]
check(len(sigs) == 1, "3 cmd_heads x harness refusal -> 1 signature (got %d)" % len(sigs))
if sigs:
    s = sigs[0]
    check((s["tool_name"], s["cmd_head"], s["error_class"]) == ("Bash", "", "harness_worktree_isolation"),
          "grouped signature is (Bash, '', harness_worktree_isolation)")
    check(s["count"] == 12 and s["qualifies"], "grouped signature pools the count and qualifies")

# "other" keeps its per-cmd split; unmatched text is not reclassified.
d = reset("other")
for head in ("cat", "sed"):
    for n in range(3):
        write(d, day(1 + n % 2), [row(head, "other", "weird failure", date=day(1 + n % 2))])
p, data = run(d)
check(sorted(s["cmd_head"] for s in data["signatures"]) == ["cat", "sed"],
      "other errors keep per-cmd_head split")
check(all(s["error_class"] == "other" for s in data["signatures"]), "other stays other")

# Rows stored as "other" with harness text are reclassified; blind legacy rows stay unknown.
d = reset("reclass")
write(d, day(1), [row("cat", "other", HARNESS, date=day(1))])
write(d, day(2), [row("cat", None, None, date=day(2))])
p, data = run(d)
classes = sorted(s["error_class"] for s in data["signatures"])
check(classes == ["harness_worktree_isolation", "unknown"], "reclassified + unknown: %s" % classes)
unk = [s for s in data["signatures"] if s["error_class"] == "unknown"]
check(unk and unk[0]["excluded"] == "unknown" and not unk[0]["qualifies"], "unknown excluded")

# A stored row with a class but no error text keeps its stored class.
d = reset("stored")
write(d, day(1), [row("echo", "zsh_no_matches", None, date=day(1))])
p, data = run(d)
check([s["error_class"] for s in data["signatures"]] == ["zsh_no_matches"],
      "stored class kept when no error text")

# Local-day counting: 6 events 20:00-23:00 local on one date span two UTC dates.
d = reset("localday")
tz = "America/New_York"  # EDT, UTC-4 in October
# 20:00-23:00 EDT on 2026-10-02 = 00:00-03:00 UTC on 2026-10-03
stamps = ["2026-10-03T00:00:00+00:00", "2026-10-03T00:30:00+00:00", "2026-10-03T01:00:00+00:00",
          "2026-10-03T01:30:00+00:00", "2026-10-03T02:00:00+00:00", "2026-10-03T02:59:00+00:00"]
for i, ts in enumerate(stamps):
    write(d, "2026-10-03", [row("cat", "other", "weird failure", sess="s%d" % (i % 2), ts=ts)])
# One more event on the UTC date before, still the same local evening.
p, data = run(d, tz=tz)
s = data["signatures"][0]
check(s["count"] == 6 and s["days"] == 1, "one local evening counts 1 day (got %s)" % s["days"])
check(not s["qualifies"], "one local evening does not qualify")

# The same stamps split across two UTC files still count as one local day.
d = reset("localday2")
for i, ts in enumerate(stamps):
    f = "2026-10-03"
    write(d, f, [row("cat", "other", "weird failure", sess="s%d" % (i % 2), ts=ts)])
write(d, "2026-10-02", [row("cat", "other", "weird failure", sess="s1",
                            ts="2026-10-02T23:30:00+00:00")])  # 19:30 EDT, 10-02 local
p, data = run(d, tz=tz)
check(data["signatures"][0]["days"] == 1, "two UTC files, one local day")

# Under UTC the same stamps are 2 UTC dates -> 2 days when files differ.
p, data = run(d, tz="UTC")
check(data["signatures"][0]["days"] == 2, "UTC machine counts UTC days")

# Rows with a missing timestamp fall back to the file date.
d = reset("nots")
r = row("cat", "other", "weird failure", date=day(1))
del r["timestamp"]
write(d, day(1), [r])
p, data = run(d)
check(data["signatures"][0]["days"] == 1 and data["signatures"][0]["first_seen"] == day(1),
      "missing timestamp falls back to file date")

# Routing: harness refusals are drafted (not an issue like hook denials) from the
# subagent rules.
spec = importlib.util.spec_from_file_location(
    "draft", os.path.join(os.path.dirname(AGG), "..", "lib", "draft_proposals.py"))
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)
mp = dp.load_map(os.path.join(os.path.dirname(AGG), "..", "lib", "signature-module-map.json"))
hsig = {"tool_name": "Bash", "cmd_head": "", "error_class": "harness_worktree_isolation"}
check(not dp.is_hook_denial(hsig, mp), "harness refusal is not routed as a hook-denial issue")
entries = [{"path": "modules/subagent-patterns/rules/subagent-patterns.md"},
           {"path": "modules/multi-agent/rules/multi-agent.md"},
           {"path": "modules/code-quality/rules/code-quality.md"}]
check(dp.pick_candidates(hsig, entries, mp) == [e["path"] for e in entries[:2]],
      "harness refusal candidates are the subagent and multi-agent rules")

print("test-signature-quality.sh: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
PY
