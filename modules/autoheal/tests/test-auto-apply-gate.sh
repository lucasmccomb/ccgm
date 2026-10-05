#!/usr/bin/env bash
# test-auto-apply-gate.sh
#
# Earned auto-apply (#1099 Phase 4.2): bin/autoheal-auto-apply.sh and
# lib/auto_apply.py, with the mode, agreement and promotion logic in
# lib/autoheal_mode.py. Runs against a fixture source repo with a bare origin
# and a fake `gh`; nothing touches GitHub, the real ~/.claude/autoheal, or
# launchctl.
#
#   g1  gate: rule_insert, validate() passes, >=10 occurrences, >=3 sessions,
#       target in auto_apply_targets; each failing axis names its reason
#   g2  shadow: every ready row gets a logged decision; the ledger, the source
#       repo and origin are unchanged and gh is never called
#   g3  agreement against review decisions (applied = accepted, rejected =
#       rejected); the run logs it; `stats` reports it
#   g4  switching to active is refused below 10 decided decisions, below 90%
#       agreement, or with a harmful would-apply; allowed at the bar, which
#       records auto_apply_promoted_at
#   g5  active: the qualifying row is applied through /autoheal-review's path
#       (PR, squash-merge, Autoheal-Id and Autoheal-Signature trailers) and
#       marked applied_by auto; the notice announces it with the undo command
#   g6  active without a promotion record runs as shadow
#   g7  3 reverts within 30 days demote active to shadow
#   g8  off does nothing; the legacy auto_apply_enabled flag migrates to
#       off or shadow, never active; the toggle retires it
#   g9  tab safety: no autoheal script hands grep a `\t` escape (GNU grep reads
#       it as a literal t), and the gate gives the same answer when the grep on
#       PATH rejects such patterns
#
# Run: bash modules/autoheal/tests/test-auto-apply-gate.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AUTO_APPLY_SH="${MODULE_ROOT}/bin/autoheal-auto-apply.sh"
MODE_PY="${MODULE_ROOT}/lib/autoheal_mode.py"
NOTICE="${MODULE_ROOT}/hooks/autoheal-session-notice.py"

PASS=0
FAIL=0
assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}
contains() { case "$1" in *"$2"*) echo yes ;; *) echo no ;; esac; }

TMP="$(mktemp -d -t autoheal-gate.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

export GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid
export GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export HOME="${TMP}/home"
mkdir -p "${HOME}"

RULE="modules/git-workflow/rules/git-workflow.md"

# --- fixture source repo + bare origin ------------------------------------------
ORIGIN="${TMP}/origin.git"
SRC="${TMP}/src"
git init -q --bare -b main "${ORIGIN}"
git init -q -b main "${SRC}"
mkdir -p "${SRC}/modules/git-workflow/rules" "${SRC}/modules/other/rules" "${SRC}/tests"
touch "${SRC}/start.sh"
printf '# Git Workflow\n\n## Shell Quoting\n\nKeep commands simple.\n' > "${SRC}/${RULE}"
printf '# Other\n\n## Section\n\nText.\n' > "${SRC}/modules/other/rules/other.md"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-no-personal-data.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-modules.sh"
git -C "${SRC}" add -A
git -C "${SRC}" commit -q -m "fixture"
git -C "${SRC}" remote add origin "${ORIGIN}"
git -C "${SRC}" push -q origin main
git -C "${SRC}" fetch -q origin
git -C "${SRC}" branch -q --set-upstream-to=origin/main main

# --- fake gh ---------------------------------------------------------------------
BIN="${TMP}/bin"
mkdir -p "${BIN}"
GHLOG="${TMP}/gh.log"
: > "${GHLOG}"
cat > "${BIN}/gh" <<'GH'
#!/usr/bin/env bash
printf '%s' "$*" | tr '\n' ' ' >> "${GHLOG}"
printf '\n' >> "${GHLOG}"
case "$1 $2" in
    "pr create")
        while [ $# -gt 0 ]; do
            [ "$1" = "--head" ] && head="$2"
            shift
        done
        git -C "${FAKE_ORIGIN}" update-ref "refs/snapshots/${head#autoheal/}" "refs/heads/${head}"
        echo "https://github.com/fixture/ccgm/pull/31" ;;
    "pr checks") echo "all checks were successful" ;;
    "pr merge") echo "merged" ;;
    "pr view") echo "abcdefabcdefabcdefabcdefabcdefabcdefabcd" ;;
    *) echo "fake gh: unexpected $*" >&2; exit 64 ;;
esac
GH
chmod +x "${BIN}/gh"
export GHLOG FAKE_ORIGIN="${ORIGIN}"
export PATH="${BIN}:${PATH}"

# --- autoheal data dir -------------------------------------------------------------
AH="${TMP}/ah"
mkdir -p "${AH}/events" "${AH}/counts"
export CCGM_AUTOHEAL_DIR="${AH}"
export CCGM_AUTOHEAL_CONFIG="${AH}/config.json"
export CCGM_AUTOHEAL_LOGS_DIR="${TMP}/logs"
export CCGM_AUTOHEAL_TODAY="2026-10-04"
export SRC

# config <json fragment merged over the base config>
config() {
    python3 - "${AH}/config.json" "${SRC}" "$1" <<'PY'
import json, sys
path, src, extra = sys.argv[1:4]
cfg = {"ccgm_repo_path": src, "auto_apply_targets": ["modules/git-workflow/rules/*.md"]}
cfg.update(json.loads(extra))
json.dump(cfg, open(path, "w"))
PY
}

seed() {
    rm -rf "${AH}/shadow"
    PYTHONPATH="${MODULE_ROOT}/lib" python3 - "${AH}" "${SRC}" <<'PY'
import json, os, sys
import draft_proposals as dp
ah, src = sys.argv[1:3]
def diff_for(target, anchor):
    old = open(os.path.join(src, target)).read()
    new = dp.insert_under_heading(old, anchor, ["- Quote globs in zsh."])
    return dp.unified_diff(target, old, new) if new is not None else ""
def row(i, n, **kw):
    target = kw.pop("target", "modules/git-workflow/rules/git-workflow.md")
    anchor = kw.pop("anchor", "Shell Quoting")
    r = {"id": i, "signature_id": i, "state": "ready", "kind": "rule_insert", "tool_name": "Bash",
         "cmd_head": "echo", "error_class": f"class_{i}", "occurrence_count": kw.get("count", 12),
         "evidence": {"count": kw.pop("count", 12), "sessions": kw.pop("sessions", 4), "days": 5,
                      "first_seen": "2026-09-20", "last_seen": "2026-10-02", "samples": ["x"]},
         "title": f"echo class_{i}: add a rule to {os.path.basename(target or 'issue')}", "target": target,
         "anchor": anchor, "insert_markdown": "- Quote globs in zsh.",
         "diff": target and diff_for(target, "Shell Quoting" if anchor == "No Such Heading" else anchor),
         "generated_at": f"2026-10-0{n}T00:00:00+00:00"}
    r.update(kw)
    return r
rows = [
    row("good00000000", 1),
    row("lowcount0000", 2, count=9),
    row("lowsess00000", 2, sessions=2),
    row("notallowed00", 3, target="modules/other/rules/other.md", anchor="Section"),
    row("badanchor000", 3, anchor="No Such Heading"),
    row("issue0000000", 3, kind="issue", target=None, anchor=None, diff=None,
        issue_title="t", issue_body="b"),
]
open(os.path.join(ah, "proposals.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY
}

run_gate() { bash "${AUTO_APPLY_SH}" 2>&1; }

decision() {
    # decision <id> <key>: the newest shadow decision for the id
    python3 - "${AH}/shadow/auto-apply.jsonl" "$1" "$2" <<'PY'
import json, sys
try:
    rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
except OSError:
    rows = []
rows = [r for r in rows if r.get("proposal_id") == sys.argv[2]]
print(rows[-1].get(sys.argv[3]) if rows else "MISSING")
PY
}

field() {
    python3 - "${AH}/proposals.jsonl" "$1" "$2" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rows = [r for r in rows if r.get("id") == sys.argv[2]]
print(rows[-1].get(sys.argv[3]) if rows else "MISSING")
PY
}

cfg_key() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))" "${AH}/config.json" "$1"; }

repo_state() { git -C "${SRC}" status --porcelain; git -C "${SRC}" branch --list; git -C "${SRC}" worktree list | wc -l; git -C "${ORIGIN}" for-each-ref; }

# --- g1 + g2: shadow decisions, no change ------------------------------------------
config '{"auto_apply_mode": "shadow"}'
seed
ledger_before="$(cat "${AH}/proposals.jsonl")"
repo_before="$(repo_state)"
: > "${GHLOG}"
out="$(run_gate)"
assert_eq "$(decision good00000000 would_apply)" "True" "g1: qualifying rule_insert -> would apply"
assert_eq "$(decision lowcount0000 would_apply)" "False" "g1: 9 occurrences -> skip"
assert_eq "$(contains "$(decision lowcount0000 reason)" "occurrences")" "yes" "g1: reason names occurrences"
assert_eq "$(decision lowsess00000 would_apply)" "False" "g1: 2 sessions -> skip"
assert_eq "$(contains "$(decision lowsess00000 reason)" "sessions")" "yes" "g1: reason names sessions"
assert_eq "$(decision notallowed00 would_apply)" "False" "g1: target outside the allowlist -> skip"
assert_eq "$(contains "$(decision notallowed00 reason)" "auto_apply_targets")" "yes" "g1: reason names the allowlist key"
assert_eq "$(decision badanchor000 would_apply)" "False" "g1: validate() failure -> skip"
assert_eq "$(contains "$(decision badanchor000 reason)" "anchor_missing")" "yes" "g1: reason carries the validate() reason"
assert_eq "$(decision issue0000000 would_apply)" "MISSING" "g1: an issue row is never an auto-apply candidate, so no decision is logged"
assert_eq "$(decision good00000000 generated_at)" "2026-10-01T00:00:00+00:00" "g2: decision keyed to the row's generated_at"
assert_eq "$(decision good00000000 mode)" "shadow" "g2: decision records the mode"
assert_eq "$(cat "${AH}/proposals.jsonl")" "${ledger_before}" "g2: shadow leaves the ledger unchanged"
assert_eq "$(repo_state)" "${repo_before}" "g2: shadow leaves the source repo and origin unchanged"
assert_eq "$(cat "${GHLOG}")" "" "g2: shadow never calls gh"
assert_eq "$(contains "${out}" "mode=shadow")" "yes" "g2: summary names shadow mode"
assert_eq "$(contains "${out}" "would_apply=1")" "yes" "g2: summary counts would-apply rows"

# --- g3: agreement against review decisions -----------------------------------------
# good: applied by review (agree); lowcount, notallowed, issue: rejected (agree);
# lowsess: applied by review (false negative); badanchor: still ready (pending).
# The issue row has no decision, so its rejection does not count.
PYTHONPATH="${MODULE_ROOT}/lib" python3 - <<'PY'
import ledger
ledger.set_state("good00000000", "applied", merged_at="2026-10-03T00:00:00+00:00")
ledger.set_state("lowsess00000", "applied", merged_at="2026-10-03T00:00:00+00:00")
for pid in ("lowcount0000", "notallowed00", "issue0000000"):
    ledger.set_state(pid, "rejected", reject_reason="Wrong fix")
PY
out="$(run_gate)"
assert_eq "$(contains "${out}" "agreement 3/4 (75%)")" "yes" "g3: the run logs agreement against review decisions"
stats="$(python3 "${MODE_PY}" stats "${AH}/config.json")"
sget() { printf '%s' "${stats}" | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
assert_eq "$(sget 'd["mode"]')" "shadow" "g3: stats mode"
assert_eq "$(sget 'd["decided"], d["agreed"], d["false_positives"], d["false_negatives"], d["pending"]')" "4 3 0 1 1" "g3: decided, agreed, fp, fn, pending"
assert_eq "$(sget 'd["ready_for_active"]')" "False" "g3: below the bar"

# --- g4: promotion bar ----------------------------------------------------------------
before="$(cat "${AH}/config.json")"
out="$(python3 "${MODE_PY}" set "${AH}/config.json" autoapply active 2>&1)"; rc=$?
assert_eq "${rc}" "3" "g4: active refused with exit 3"
assert_eq "$(contains "${out}" "4 of 10 decided decisions")" "yes" "g4: refusal says how many decisions are missing"
assert_eq "$(contains "${out}" "agreement 75% is below 90%")" "yes" "g4: refusal names the agreement rate"
assert_eq "$(cat "${AH}/config.json")" "${before}" "g4: a refused switch leaves the config unchanged"

# Synthetic histories: n decisions, k agreeing, h harmful would-applies.
history() {
    python3 - "${AH}" "$1" "$2" "$3" <<'PY'
import json, os, sys
ah, n, k, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
rows, decs = [], []
for i in range(n):
    pid = "h%011d" % i
    gen = "2026-09-01T00:00:00+00:00"
    agree = i < k
    harmful = i < h
    # would-apply rows the user applied agree; one the user rejected is a false positive.
    if agree:
        state = "measured" if harmful else "applied"
    else:
        state = "rejected"
    row = {"id": pid, "signature_id": pid, "state": state, "kind": "rule_insert", "generated_at": gen}
    if harmful:
        row["outcome"] = "harmful"
    rows.append(row)
    decs.append({"ts": gen, "proposal_id": pid, "generated_at": gen, "would_apply": True,
                 "reason": "passed", "mode": "shadow"})
os.makedirs(os.path.join(ah, "shadow"), exist_ok=True)
open(os.path.join(ah, "proposals.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
open(os.path.join(ah, "shadow", "auto-apply.jsonl"), "w").write("".join(json.dumps(d) + "\n" for d in decs))
PY
}
try_active() { python3 "${MODE_PY}" set "${AH}/config.json" autoapply active 2>&1; }
config '{"auto_apply_mode": "shadow"}'
history 9 9 0
out="$(try_active)"; rc=$?
assert_eq "${rc}" "3" "g4: 9 decisions at 100% refused"
history 10 8 0
out="$(try_active)"; rc=$?
assert_eq "${rc}" "3" "g4: 10 decisions at 80% refused"
history 10 10 1
out="$(try_active)"; rc=$?
assert_eq "${rc}" "3" "g4: a harmful would-apply refuses"
assert_eq "$(contains "${out}" "1 would-apply decision(s) later measured harmful or reverted")" "yes" "g4: refusal names the harmful decision"
history 10 9 0
out="$(try_active)"; rc=$?
assert_eq "${rc}" "0" "g4: 10 decisions at 90% with no harmful is allowed"
assert_eq "$(cfg_key auto_apply_mode)" "active" "g4: mode written"
assert_eq "$([ "$(cfg_key auto_apply_promoted_at)" != "None" ] && echo set)" "set" "g4: promotion recorded"
assert_eq "$(cfg_key ccgm_repo_path)" "${SRC}" "g4: other keys kept"
python3 "${MODE_PY}" set "${AH}/config.json" autoapply shadow >/dev/null
assert_eq "$(cfg_key auto_apply_promoted_at)" "None" "g4: leaving active clears the promotion record"

# --- g5: active applies through the review path -------------------------------------
config '{"auto_apply_mode": "active", "auto_apply_promoted_at": "2026-09-30T00:00:00+00:00"}'
seed
: > "${GHLOG}"
out="$(run_gate)"
assert_eq "$(field good00000000 state)" "applied" "g5: qualifying row applied"
assert_eq "$(field good00000000 applied_by)" "auto" "g5: row marked applied_by auto"
assert_eq "$(field good00000000 pr_url)" "https://github.com/fixture/ccgm/pull/31" "g5: PR recorded"
assert_eq "$([ "$(field good00000000 baseline_rate)" != "MISSING" ] && echo kept)" "kept" "g5: baseline fields written by the review path"
for pid in lowcount0000 lowsess00000 notallowed00 badanchor000 issue0000000; do
    assert_eq "$(field "${pid}" state)" "ready" "g5: ${pid} not applied"
done
assert_eq "$(grep -c 'pr create' "${GHLOG}")" "1" "g5: exactly one PR opened"
assert_eq "$(contains "$(cat "${GHLOG}")" "--admin")" "no" "g5: never --admin"
msg="$(git -C "${ORIGIN}" log refs/snapshots/good00000000 -1 --format=%B)"
assert_eq "$(contains "${msg}" "Autoheal-Id: good00000000")" "yes" "g5: Autoheal-Id trailer"
assert_eq "$(contains "${msg}" "Autoheal-Signature: Bash|echo|class_good00000000")" "yes" "g5: Autoheal-Signature trailer"
assert_eq "$(git -C "${SRC}" status --porcelain; git -C "${SRC}" branch --list)" "$(printf '* main')" "g5: source checkout untouched"
assert_eq "$(contains "${out}" "applied=1")" "yes" "g5: summary counts the apply"

notice="$(printf '{"cwd":"/tmp/project"}' | CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR="${TMP}/no-agents" CCGM_AUTOHEAL_REAL_HOME="${HOME}" CCGM_AUTOHEAL_NOW="2026-10-04T12:00:00+00:00" python3 "${NOTICE}")"
nmsg="$(printf '%s' "${notice}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("systemMessage",""))')"
assert_eq "$(contains "${nmsg}" "applied 1 fix: echo class_good00000000: add a rule to git-workflow.md (undo: /autoheal-review revert good00000000)")" "yes" "g5: notice announces the auto-applied fix with the undo command"

# --- g6: active with no promotion record runs as shadow --------------------------------
config '{"auto_apply_mode": "active"}'
seed
: > "${GHLOG}"
out="$(run_gate)"
assert_eq "$(cat "${GHLOG}")" "" "g6: hand-set active without promotion calls no gh"
assert_eq "$(field good00000000 state)" "ready" "g6: nothing applied"
assert_eq "$(decision good00000000 would_apply)" "True" "g6: decisions still logged"
assert_eq "$(contains "${out}" "not promoted")" "yes" "g6: log says why active did not run"

# --- g7: 3 reverts in 30 days demote to shadow ----------------------------------------
config '{"auto_apply_mode": "active", "auto_apply_promoted_at": "2026-09-01T00:00:00+00:00"}'
seed
python3 - "${AH}/proposals.jsonl" <<'PY'
import json, sys
with open(sys.argv[1], "a") as fh:
    for i, day in enumerate(("2026-09-10", "2026-09-20", "2026-10-01")):
        fh.write(json.dumps({"id": "rev%09d" % i, "state": "reverted", "kind": "rule_insert",
                             "reverted_at": day + "T00:00:00+00:00"}) + "\n")
PY
: > "${GHLOG}"
out="$(run_gate)"
assert_eq "$(cfg_key auto_apply_mode)" "shadow" "g7: demoted to shadow"
assert_eq "$(contains "$(cfg_key auto_apply_demoted_reason)" "3 reverts in 30 days")" "yes" "g7: demotion reason recorded"
assert_eq "$(cfg_key auto_apply_promoted_at)" "None" "g7: promotion record cleared"
assert_eq "$(cat "${GHLOG}")" "" "g7: nothing applied after demotion"
assert_eq "$(contains "${out}" "demoted")" "yes" "g7: log names the demotion"
# Two reverts in the window (one is 40 days old) do not demote.
config '{"auto_apply_mode": "active", "auto_apply_promoted_at": "2026-09-01T00:00:00+00:00"}'
seed
python3 - "${AH}/proposals.jsonl" <<'PY'
import json, sys
with open(sys.argv[1], "a") as fh:
    for i, day in enumerate(("2026-08-25", "2026-09-20", "2026-10-01")):
        fh.write(json.dumps({"id": "rev%09d" % i, "state": "reverted", "kind": "rule_insert",
                             "reverted_at": day + "T00:00:00+00:00"}) + "\n")
PY
run_gate >/dev/null
assert_eq "$(cfg_key auto_apply_mode)" "active" "g7: 2 reverts within 30 days keep active"

# --- g8: off, and the legacy flag ------------------------------------------------------
config '{"auto_apply_mode": "off"}'
seed
rm -rf "${AH}/shadow"
: > "${GHLOG}"
run_gate >/dev/null
assert_eq "$([ -e "${AH}/shadow/auto-apply.jsonl" ] && echo logged || echo none)" "none" "g8: off logs no decisions"
assert_eq "$(cat "${GHLOG}")" "" "g8: off calls no gh"
legacy() {
    printf '%s\n' "$1" > "${TMP}/legacy.json"
    PYTHONPATH="${MODULE_ROOT}/lib" python3 -c "import autoheal_mode as m, sys; print(m.read_auto_apply_mode(sys.argv[1]))" "${TMP}/legacy.json"
}
assert_eq "$(legacy '{"auto_apply_enabled": true}')" "shadow" "g8: legacy true reads as shadow, not active"
assert_eq "$(legacy '{"auto_apply_enabled": "active"}')" "shadow" "g8: legacy active reads as shadow"
assert_eq "$(legacy '{"auto_apply_enabled": "shadow"}')" "shadow" "g8: legacy shadow reads as shadow"
assert_eq "$(legacy '{"auto_apply_enabled": false}')" "off" "g8: legacy false reads as off"
assert_eq "$(legacy '{}')" "off" "g8: default off"
assert_eq "$(legacy '{"auto_apply_enabled": true, "auto_apply_mode": "off"}')" "off" "g8: auto_apply_mode wins over the legacy flag"
assert_eq "$(legacy '{"auto_apply_mode": "bogus"}')" "off" "g8: junk fails closed to off"
printf '{"auto_apply_enabled": true, "email_enabled": false}\n' > "${TMP}/legacy.json"
out="$(python3 "${MODE_PY}" set "${TMP}/legacy.json" autoapply shadow)"
assert_eq "${out}" "set auto_apply_mode = shadow" "g8: toggle confirms the new key"
assert_eq "$(python3 -c "import json; d=json.load(open('${TMP}/legacy.json')); print(d.get('auto_apply_mode'), 'auto_apply_enabled' in d, d.get('email_enabled'))")" "shadow False False" "g8: toggle retires the legacy key and keeps the rest"
assert_eq "$(python3 "${MODE_PY}" status "${TMP}/legacy.json" autoapply)" "auto_apply_mode = shadow" "g8: status prints the mode"
python3 "${MODE_PY}" set "${TMP}/legacy.json" autoapply bogus >/dev/null 2>&1
assert_eq "$?" "2" "g8: junk value rejected with exit 2"

# --- g9: tab safety -----------------------------------------------------------------------
hits="$(grep -rnE 'grep.*\\t' "${MODULE_ROOT}/bin" "${MODULE_ROOT}/hooks" "${MODULE_ROOT}/lib" 2>/dev/null | grep -v '^[^:]*:[0-9]*:[[:space:]]*#' || true)"
assert_eq "${hits}" "" "g9: no autoheal script passes a \\t escape to grep"
GNUBIN="${TMP}/gnu-like"
mkdir -p "${GNUBIN}"
REAL_GREP="$(command -v grep)"
cat > "${GNUBIN}/grep" <<EOF
#!/usr/bin/env bash
# GNU grep reads \\t in a pattern as a literal t; refuse such patterns outright.
for arg in "\$@"; do
    case "\${arg}" in *'\\t'*) echo "gnu-like grep: \\\\t is a literal t here" >&2; exit 2 ;; esac
done
exec "${REAL_GREP}" "\$@"
EOF
chmod +x "${GNUBIN}/grep"
config '{"auto_apply_mode": "shadow"}'
seed
PATH="${GNUBIN}:${PATH}" run_gate >/dev/null
assert_eq "$(decision good00000000 would_apply)|$(decision lowcount0000 would_apply)" "True|False" "g9: same decisions with a GNU-like grep first on PATH"

echo ""
echo "test-auto-apply-gate.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
