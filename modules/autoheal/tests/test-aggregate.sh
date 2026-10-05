#!/usr/bin/env bash
# Test suite for bin/autoheal-aggregate.py (#1099 Phase 2.1): the
# deterministic signature aggregator.
#
# Covers:
#   - 612 zsh-quoting rows over 5 sessions / 3 days rank first and qualify.
#   - 4 occurrences, or a single session, or a single day, do not qualify.
#   - Rates per 100 calls come from counts/{date}.json.
#   - Pre-#1112 rows (no error_class) become "unknown" and never qualify.
#   - user_interrupt rows are kept apart from tool_failure signatures.
#   - Snoozed signatures and signatures in proposals.jsonl are excluded;
#     a missing ledger is fine.
#   - Rows older than the 14-day window are ignored; samples are deduped,
#     redacted and <= 300 chars.
#   - signature_id is sha256 of the tuple, first 12 hex chars.
#   - signature_rate() works over an arbitrary window.
#   - Config overrides the bar.
#   - 30 days of ~3k rows aggregate in under 2 seconds.
#   - The script imports no network module.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AGG="${MODULE_ROOT}/bin/autoheal-aggregate.py"

TMP=$(mktemp -d -t autoheal_agg.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT
export AGG TMP

python3 - <<'PY'
import datetime as dt
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import time

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


def day(n):
    return (END - dt.timedelta(days=n)).isoformat()


def reset(name):
    d = os.path.join(BASE, name)
    os.environ["CCGM_AUTOHEAL_DIR"] = d
    os.environ["CCGM_AUTOHEAL_CONFIG"] = os.path.join(d, "config.json")
    os.makedirs(os.path.join(d, "events"), exist_ok=True)
    os.makedirs(os.path.join(d, "counts"), exist_ok=True)
    return d


ERR_FOR = {"zsh_no_matches": "zsh: no matches found: *.x",
           "command_not_found": "x: command not found"}


def row(kind="tool_failure", tool="Bash", head="echo", cls="zsh_no_matches",
        sess="s1", cwd="/Users/x/code/ccgm-workspaces/ccgm-w0/ccgm-w0-c1",
        err=None, legacy=False):
    r = {"kind": kind, "timestamp": "2026-10-01T00:00:00Z", "session_id": sess,
         "tool_name": tool, "cwd": cwd, "redacted_command": "echo ==",
         "exit_code": 1}
    if err is None:  # error text that classifies as `cls` (rows are reclassified from it)
        err = ERR_FOR.get(cls, "synthetic failure")
    if not legacy:
        r.update({"error": err, "error_class": cls,
                  "cmd_head": head if tool == "Bash" else None})
    return r


def write(d, date, rows):
    with open(os.path.join(d, "events", date + ".jsonl"), "a") as fh:
        for r in rows:
            r["timestamp"] = date + "T12:00:00+00:00"  # days count by row timestamp
            fh.write(json.dumps(r) + "\n")


def counts(d, date, c):
    with open(os.path.join(d, "counts", date + ".json"), "w") as fh:
        json.dump(c, fh)


def run(d, extra=()):
    p = subprocess.run([sys.executable, AGG, "--date", END.isoformat(), *extra],
                       capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
    out = os.path.join(d, "signatures", END.isoformat() + ".json")
    data = json.load(open(out)) if os.path.isfile(out) else None
    return p, data


def sid(tool, head, cls):
    return hashlib.sha256("\x1f".join([tool, head, cls]).encode()).hexdigest()[:12]


def find(data, tool, head, cls):
    for s in data["signatures"]:
        if (s["tool_name"], s["cmd_head"], s["error_class"]) == (tool, head, cls):
            return s
    return None


# ---- main fixture -------------------------------------------------------
d = reset("main")
zsh_days = [day(1), day(2), day(3)]
for i in range(612):
    write(d, zsh_days[i % 3], [row(sess="s%d" % (i % 5))])
for i in range(4):  # 4 occurrences, 4 sessions, 2 days
    write(d, day(i % 2), [row(head="rg", cls="command_not_found", sess="r%d" % i,
                                err="rg: command not found")])
for i in range(20):  # many occurrences, one session
    write(d, day(i % 3), [row(head="git add", cls="other", sess="only")])
for i in range(10):  # many occurrences, many sessions, one day
    write(d, day(1), [row(head="npm", cls="other", sess="n%d" % i)])
for i in range(300):  # legacy blind rows
    write(d, day(i % 4), [row(sess="L%d" % (i % 6), legacy=True)])
for i in range(50):  # outside the window
    write(d, day(20), [row(head="old", cls="other", sess="o%d" % (i % 4))])
for i in range(8):  # interrupts
    write(d, day(i % 3), [row(kind="user_interrupt", head="sleep", cls="other",
                              sess="i%d" % (i % 4), err="interrupted")])
long_err = "E" * 500
write(d, day(1), [row(head="curl", cls="other", sess="c1", err=long_err),
                  row(head="curl", cls="other", sess="c2", err=long_err),
                  row(head="curl", cls="other", sess="c1", err="boom 1"),
                  row(head="curl", cls="other", sess="c2", err="boom 2"),
                  row(head="curl", cls="other", sess="c1", err="boom 3"),
                  row(head="curl", cls="other", sess="c2",
                      err="token ghp_" + "a" * 36 + " leaked")])
write(d, day(2), [row(head="curl", cls="other", sess="c3", err="boom 4")])
for dd in range(0, 14):
    counts(d, day(dd), {"Bash": 1000, "Read": 500})
for i in range(6):
    write(d, day(i % 2), [row(head="led", cls="other", sess="l%d" % i)])

p, data = run(d)
check(p.returncode == 0, "exit 0 (got %s: %s)" % (p.returncode, p.stderr))
check(data is not None, "signatures file written")
if data:
    sigs = data["signatures"]
    z = find(data, "Bash", "", "zsh_no_matches")
    check(z is not None, "zsh signature present")
    check(sigs[0] is z, "zsh signature ranks first")
    if z:
        check(z["count"] == 612, "zsh count 612, got %s" % z["count"])
        check(z["sessions"] == 5, "zsh sessions 5")
        check(z["days"] == 3, "zsh days 3")
        check(z["repos"] == 1, "zsh repos 1, got %s" % z["repos"])
        check(z["qualifies"] is True, "zsh qualifies")
        check(z["signature_id"] == sid("Bash", "", "zsh_no_matches"), "signature_id hash")
        check(z["first_seen"] == day(3) and z["last_seen"] == day(1), "first/last seen")
        check(z["calls"] == 14000, "calls from counts")
        check(abs(z["rate_per_100_calls"] - 612 / 14000 * 100) < 1e-6,
              "rate from counts, got %s" % z.get("rate_per_100_calls"))
    r = find(data, "Bash", "rg", "command_not_found")
    check(r and r["count"] == 4 and not r["qualifies"], "4 occurrences do not qualify")
    g = find(data, "Bash", "git add", "other")
    check(g and g["sessions"] == 1 and not g["qualifies"], "single session does not qualify")
    n = find(data, "Bash", "npm", "other")
    check(n and n["days"] == 1 and not n["qualifies"], "single day does not qualify")
    u = find(data, "Bash", "", "unknown")
    check(u is not None and not u["qualifies"], "legacy rows -> unknown, not qualifying")
    check(find(data, "Bash", "old", "other") is None, "out-of-window rows ignored")
    check(find(data, "Bash", "sleep", "other") is None, "interrupts not in signatures")
    ints = data.get("interrupts", [])
    check(len(ints) == 1 and ints[0]["count"] == 8 and ints[0]["tool_name"] == "Bash",
          "interrupts kept separately: %s" % ints)
    c = find(data, "Bash", "curl", "other")
    check(c is not None, "curl present")
    if c:
        s = c["samples"]
        check(len(s) <= 3, "<= 3 samples")
        check(len(set(s)) == len(s), "samples deduped")
        check(all(len(x) <= 300 for x in s), "samples <= 300 chars")
        check(not any("ghp_" + "a" * 36 in x for x in s), "samples redacted")
    check(find(data, "Bash", "led", "other")["qualifies"], "ledger absent -> qualifies")
    ranks = [s["count"] * s["sessions"] for s in sigs]
    check(ranks == sorted(ranks, reverse=True), "ranked by count x sessions")

# ---- ledger exclusion ---------------------------------------------------
with open(os.path.join(d, "proposals.jsonl"), "w") as fh:
    fh.write(json.dumps({"id": "x", "state": "ready",
                         "signature_id": sid("Bash", "led", "other")}) + "\n")
    fh.write("not json\n")
p, data = run(d)
check(p.returncode == 0, "tolerates garbage ledger line")
lg = find(data, "Bash", "led", "other")
check(lg and not lg["qualifies"] and lg.get("excluded") == "covered", "ledger-covered excluded")

# ---- config overrides the bar ------------------------------------------
with open(os.environ["CCGM_AUTOHEAL_CONFIG"], "w") as fh:
    json.dump({"aggregation": {"min_occurrences": 3}}, fh)
p, data = run(d)
check(find(data, "Bash", "rg", "command_not_found")["qualifies"], "config lowers occurrence bar")
os.unlink(os.environ["CCGM_AUTOHEAL_CONFIG"])

# ---- reusable rate function --------------------------------------------
spec = importlib.util.spec_from_file_location("agg", AGG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
res = mod.signature_rate(d, ("Bash", "", "zsh_no_matches"),
                         dt.date.fromisoformat(day(3)), dt.date.fromisoformat(day(1)))
check(res["occurrences"] == 612 and res["calls"] == 3000, "signature_rate window: %s" % res)
check(abs(res["rate_per_100_calls"] - 612 / 3000 * 100) < 1e-6, "signature_rate value")
res0 = mod.signature_rate(d, ("Bash", "", "zsh_no_matches"),
                          dt.date.fromisoformat(day(40)), dt.date.fromisoformat(day(30)))
check(res0["occurrences"] == 0 and res0["rate_per_100_calls"] is None, "no calls -> rate None")

# ---- performance: 30 days, ~3k friction rows ---------------------------
d = reset("perf")
random.seed(7)
heads = [("", "zsh_no_matches"), ("git add", "other"), ("rg", "command_not_found"),
         ("npm", "other"), ("curl", "other")]
for i in range(3000):
    h, c = random.choice(heads)
    write(d, day(random.randrange(30)), [row(head=h, cls=c, sess="s%d" % random.randrange(60),
                                              cwd="/Users/x/code/r%d" % random.randrange(5))])
for dd in range(30):
    counts(d, day(dd), {"Bash": 3000, "Read": 1500})
t = time.time()
p, data = run(d)
el = time.time() - t
check(p.returncode == 0 and data is not None, "perf run ok")
check(el < 2.0, "30 days at real scale under 2s (took %.2fs)" % el)

# ---- no network ---------------------------------------------------------
src = open(AGG).read()
check(not any(m in src for m in ("urllib", "http.client", "import socket", "requests", "ssl")),
      "no network imports")

print("test-aggregate.sh: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
PY
