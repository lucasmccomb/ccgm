#!/usr/bin/env bash
# test-outcomes.sh
#
# Outcome measurement at +14 days (#1099 Phase 4.1). bin/autoheal-aggregate.py
# measures every `applied` ledger row whose 14-day post-merge window has ended,
# compares the post-merge failure rate with the stored baseline_rate, and moves
# the row to `measured` with an outcome:
#
#   o1  rate down 80%                            effective
#   o2  rate down 25%                            ineffective
#   o3  rate up                                  harmful
#   o4  rate down, but a new signature appears
#       on the same cmd_head                     harmful (new_signatures listed)
#   o5  no tool calls counted: occurrences
#       compared instead                         effective
#   o6  nothing to compare against               unmeasurable
#   o7  post window not over yet                 stays applied
#   o8  an issue row (no merge)                  stays applied
#   o9  a second run changes nothing
#
# Then the harmful rows go through bin/autoheal-auto-apply.sh:
#
#   r1  shadow: no git or gh call, rows stay measured, notice flags them
#   r2  active: a revert PR for the Autoheal-Id trailer commit is opened,
#       merged and its branch deleted (fake gh, fixture bare origin); the row
#       becomes reverted; a harmful row with no trailer commit stays measured
#       with a revert_error
#   r3  the session notice reports the revert
#
# Nothing touches GitHub, the real ~/.claude/autoheal, or launchctl.
#
# Run: bash modules/autoheal/tests/test-outcomes.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AGG="${MODULE_ROOT}/bin/autoheal-aggregate.py"
AUTO_APPLY_SH="${MODULE_ROOT}/bin/autoheal-auto-apply.sh"
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

TMP="$(mktemp -d -t autoheal-outcomes.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

export GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid
export GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export HOME="${TMP}/home"
mkdir -p "${HOME}"

TODAY="2026-10-04"
RULE="modules/git-workflow/rules/git-workflow.md"

# --- fixture source repo: origin/main carries one autoheal trailer commit ----
ORIGIN="${TMP}/origin.git"
SRC="${TMP}/src"
git init -q --bare -b main "${ORIGIN}"
git init -q -b main "${SRC}"
mkdir -p "${SRC}/modules/git-workflow/rules" "${SRC}/tests"
touch "${SRC}/start.sh"
printf '# Git Workflow\n\n## Shell Quoting\n\nKeep commands simple.\n' > "${SRC}/${RULE}"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-no-personal-data.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-modules.sh"
git -C "${SRC}" add -A
git -C "${SRC}" commit -q -m "fixture"
printf '# Git Workflow\n\n## Shell Quoting\n\n- Never pipe rm into sudo.\n\nKeep commands simple.\n' > "${SRC}/${RULE}"
git -C "${SRC}" commit -q -a -F - <<'MSG'
#auto: apply autoheal proposal harm00000000

Adds a rule under "Shell Quoting".

Autoheal-Id: harm00000000
Autoheal-Signature: Bash|rm|permission_denied
MSG
TRAILER_SHA="$(git -C "${SRC}" rev-parse HEAD)"
git -C "${SRC}" commit -q --allow-empty -m "later work on main"
git -C "${SRC}" remote add origin "${ORIGIN}"
git -C "${SRC}" push -q origin main
git -C "${SRC}" fetch -q origin
git -C "${SRC}" branch -q --set-upstream-to=origin/main main

# --- fake gh ----------------------------------------------------------------
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
        echo "https://github.com/fixture/ccgm/pull/21" ;;
    "pr checks") echo "all checks were successful" ;;
    "pr merge") echo "merged" ;;
    "pr view") echo "fedcba9876543210fedcba9876543210fedcba98" ;;
    *) echo "fake gh: unexpected $*" >&2; exit 64 ;;
esac
GH
chmod +x "${BIN}/gh"
export GHLOG FAKE_ORIGIN="${ORIGIN}"
export PATH="${BIN}:${PATH}"

# --- autoheal data dir --------------------------------------------------------
AH="${TMP}/ah"
mkdir -p "${AH}/events" "${AH}/counts"
export CCGM_AUTOHEAL_DIR="${AH}"
export CCGM_AUTOHEAL_CONFIG="${AH}/config.json"
export CCGM_AUTOHEAL_LOGS_DIR="${TMP}/logs"
export CCGM_AUTOHEAL_TODAY="${TODAY}"
export SRC

config() {
    # config <auto_apply_mode> [promoted]
    python3 - "${AH}/config.json" "$1" "${2:-}" "${SRC}" <<'PY'
import json, sys
path, mode, promoted, src = sys.argv[1:5]
cfg = {"ccgm_repo_path": src, "auto_apply_mode": mode}
if promoted:
    cfg["auto_apply_promoted_at"] = "2026-09-01T00:00:00+00:00"
json.dump(cfg, open(path, "w"))
PY
}

seed() {
    python3 - "${AH}" <<'PY'
import datetime as dt, hashlib, json, os, sys
ah = sys.argv[1]
merged = "2026-09-14T10:00:00+00:00"           # post window 09-15 .. 09-28, over by 10-04
recent = "2026-09-24T10:00:00+00:00"           # post window ends 10-08: not due
def row(i, head, cls, baseline, tool="Bash", merged_at=merged, **kw):
    r = {"id": i, "signature_id": hashlib.sha256("\x1f".join((tool, head, cls)).encode()).hexdigest()[:12], "state": "applied", "kind": "rule_insert", "tool_name": tool,
         "cmd_head": head, "error_class": cls, "title": f"{head} {cls}: add a rule to git-workflow.md",
         "target": "modules/git-workflow/rules/git-workflow.md", "merged_at": merged_at,
         "applied_at": merged_at, "baseline_rate": baseline, "baseline_occurrences": 8,
         "pr_url": "https://github.com/fixture/ccgm/pull/1", "generated_at": "2026-09-10T00:00:00+00:00"}
    r.update(kw)
    return r
rows = [
    row("eff000000000", "echo", "zsh_no_match", 5.0),
    row("ineff0000000", "cp", "interactive_prompt", 2.0),
    row("harm00000000", "rm", "permission_denied", 2.0),
    row("newsig000000", "git", "merge_conflict", 4.0),
    row("edit00000000", "", "string_not_found", None, tool="Edit", baseline_occurrences=8),
    row("unmeas000000", "", "file_missing", None, tool="Write", baseline_occurrences=0),
    row("recent000000", "ls", "not_found", 3.0, merged_at=recent),
    {"id": "issue0000000", "signature_id": "issue0000000", "state": "applied", "kind": "issue",
     "issue_url": "https://github.com/fixture/ccgm/issues/3", "generated_at": "2026-09-01T00:00:00+00:00"},
    {"id": "ready0000000", "signature_id": "ready0000000", "state": "ready", "kind": "rule_insert",
     "generated_at": "2026-10-01T00:00:00+00:00"},
]
open(os.path.join(ah, "proposals.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))

def fail(day, tool, head, cls, n, sess="s1"):
    path = os.path.join(ah, "events", day + ".jsonl")
    with open(path, "a") as fh:
        for k in range(n):
            fh.write(json.dumps({"kind": "tool_failure", "tool_name": tool, "cmd_head": head,
                                 "error_class": cls, "session_id": f"{sess}-{k}"}) + "\n")
# 200 Bash calls in the post window (two days of 100).
for day in ("2026-09-16", "2026-09-20"):
    json.dump({"Bash": 100}, open(os.path.join(ah, "counts", day + ".json"), "w"))
fail("2026-09-16", "Bash", "echo", "zsh_no_match", 2)        # 1.0 vs 5.0 -> 20% -> effective
fail("2026-09-17", "Bash", "cp", "interactive_prompt", 3)    # 1.5 vs 2.0 -> 75% -> ineffective
fail("2026-09-18", "Bash", "rm", "permission_denied", 6)     # 3.0 vs 2.0 -> harmful
fail("2026-09-19", "Bash", "git", "merge_conflict", 1)       # 0.5 vs 4.0 -> would be effective ...
fail("2026-09-19", "Bash", "git", "network_error", 2)        # ... but a new git signature appeared
fail("2026-09-05", "Bash", "git", "auth_failed", 3)          # in the baseline window: not new
fail("2026-09-21", "Bash", "git", "auth_failed", 3)
fail("2026-09-22", "Edit", "", "string_not_found", 2)        # no Edit calls counted: 2 vs 8 occurrences
# Failures outside the post window are ignored.
fail("2026-09-14", "Bash", "echo", "zsh_no_match", 40)
fail("2026-09-29", "Bash", "echo", "zsh_no_match", 40)
PY
}

field() {
    # field <id> <key>: the newest row with the id
    python3 - "${AH}/proposals.jsonl" "$1" "$2" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rows = [r for r in rows if r.get("id") == sys.argv[2]]
print(rows[-1].get(sys.argv[3]) if rows else "MISSING")
PY
}

# --- o1..o8: one aggregator run measures every due row --------------------------
config off
seed
out="$(python3 "${AGG}" --date "${TODAY}" 2>&1)"
assert_eq "$?" "0" "o0: aggregator exits 0"
assert_eq "$(contains "${out}" "measured 6")" "yes" "o0: aggregator reports how many rows it measured"

assert_eq "$(field eff000000000 state)" "measured" "o1: due row becomes measured"
assert_eq "$(field eff000000000 outcome)" "effective" "o1: rate down 80% is effective"
assert_eq "$(field eff000000000 post_rate)" "1.0" "o1: post_rate over the 14 days after merge"
assert_eq "$(field eff000000000 post_window)" "['2026-09-15', '2026-09-28']" "o1: post window recorded"
assert_eq "$(field eff000000000 measured_at)" "2026-10-04" "o1: measured_at recorded"

assert_eq "$(field ineff0000000 outcome)" "ineffective" "o2: rate down 25% is ineffective"
assert_eq "$(field ineff0000000 post_rate)" "1.5" "o2: post_rate"

assert_eq "$(field harm00000000 outcome)" "harmful" "o3: rate up is harmful"
assert_eq "$(field harm00000000 post_rate)" "3.0" "o3: post_rate"

assert_eq "$(field newsig000000 outcome)" "harmful" "o4: a new signature on the same cmd_head is harmful"
assert_eq "$(field newsig000000 new_signatures)" "['Bash|git|network_error']" "o4: only signatures absent from the baseline window count as new"

assert_eq "$(field edit00000000 outcome)" "effective" "o5: no counted calls: occurrences compared (2 vs 8)"
assert_eq "$(field unmeas000000 outcome)" "unmeasurable" "o6: no baseline to compare against"

assert_eq "$(field recent000000 state)" "applied" "o7: post window still open: stays applied"
assert_eq "$(field issue0000000 state)" "applied" "o8: an issue row is never measured"
assert_eq "$(field ready0000000 state)" "ready" "o8: a ready row is untouched"

before="$(cat "${AH}/proposals.jsonl")"
out="$(python3 "${AGG}" --date "${TODAY}" 2>&1)"
assert_eq "$(cat "${AH}/proposals.jsonl")" "${before}" "o9: a second run changes nothing"

# --- r1: shadow flags harmful rows and changes nothing ---------------------------
config shadow
src_before="$(git -C "${SRC}" status --porcelain; git -C "${SRC}" branch --list; git -C "${ORIGIN}" for-each-ref)"
: > "${GHLOG}"
out="$(bash "${AUTO_APPLY_SH}" 2>&1)"
assert_eq "$(cat "${GHLOG}")" "" "r1: shadow makes no gh call"
assert_eq "$(field harm00000000 state)" "measured" "r1: shadow leaves the harmful row measured"
assert_eq "$(git -C "${SRC}" status --porcelain; git -C "${SRC}" branch --list; git -C "${ORIGIN}" for-each-ref)" "${src_before}" "r1: shadow touches no repo"
assert_eq "$(contains "${out}" "harmful")" "yes" "r1: the run log names the harmful rows"

notice="$(printf '{"cwd":"/tmp/project"}' | CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR="${TMP}/no-agents" CCGM_AUTOHEAL_REAL_HOME="${HOME}" CCGM_AUTOHEAL_NOW="${TODAY}T12:00:00+00:00" PATH="/usr/bin:/bin:$(dirname "$(command -v python3)")" python3 "${NOTICE}")"
msg="$(printf '%s' "${notice}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("systemMessage",""))')"
assert_eq "$(contains "${msg}" "rm permission_denied: add a rule to git-workflow.md looks harmful (2.0 → 3.0 per 100 calls)")" "yes" "r1: notice flags the harmful fix with its rates"
assert_eq "$(contains "${msg}" "/autoheal-review revert harm00000000")" "yes" "r1: notice offers the revert command"
assert_eq "$(contains "${msg}" "cp interactive_prompt: add a rule to git-workflow.md is ineffective (2.0 → 1.5 per 100 calls)")" "yes" "r1: notice reports the ineffective fix"
assert_eq "$(contains "${msg}" "/autoheal-review redraft ineff0000000")" "yes" "r1: notice offers a redraft for the ineffective fix"
assert_eq "$(contains "${msg}" "eff000000000")" "no" "r1: an effective fix is not announced"
rm -f "${AH}/notice-sentinel"

# --- r2: active opens and merges a revert PR -------------------------------------
config active promoted
: > "${GHLOG}"
out="$(bash "${AUTO_APPLY_SH}" 2>&1)"
assert_eq "$(field harm00000000 state)" "reverted" "r2: active reverts the harmful row"
assert_eq "$(field harm00000000 revert_pr_url)" "https://github.com/fixture/ccgm/pull/21" "r2: row stores the revert PR"
assert_eq "$(field harm00000000 reverted_commit)" "${TRAILER_SHA}" "r2: the Autoheal-Id trailer commit is the one reverted"
assert_eq "$(field harm00000000 reverted_by)" "auto" "r2: an automatic revert is recorded as such"
assert_eq "$(bool="$(field harm00000000 reverted_at)"; [ -n "${bool}" ] && [ "${bool}" != "None" ] && echo set)" "set" "r2: reverted_at recorded"
gh_calls="$(cat "${GHLOG}")"
assert_eq "$(contains "${gh_calls}" "pr create --base main --head autoheal/revert-harm00000000")" "yes" "r2: revert PR opened from autoheal/revert-<id>"
assert_eq "$(contains "${gh_calls}" "pr merge https://github.com/fixture/ccgm/pull/21 --squash")" "yes" "r2: revert PR squash-merged"
assert_eq "$(contains "${gh_calls}" "--admin")" "no" "r2: never --admin"
snap_msg="$(git -C "${ORIGIN}" log refs/snapshots/revert-harm00000000 -1 --format=%B)"
assert_eq "$(contains "${snap_msg}" "This reverts commit ${TRAILER_SHA}")" "yes" "r2: the revert commit names the trailer commit"
assert_eq "$(contains "${snap_msg}" "Autoheal-Revert: harm00000000")" "yes" "r2: revert commit carries an Autoheal-Revert trailer"
assert_eq "$(contains "${snap_msg}" "Autoheal-Id:")" "no" "r2: revert commit does not carry Autoheal-Id (it would match a later search)"
assert_eq "$(git -C "${ORIGIN}" show "refs/snapshots/revert-harm00000000:${RULE}" | grep -c 'Never pipe rm into sudo')" "0" "r2: the rule line is gone in the revert"
assert_eq "$(git -C "${ORIGIN}" branch --list 'autoheal/revert-*')" "" "r2: remote revert branch deleted after merge"
assert_eq "$(git -C "${SRC}" status --porcelain; git -C "${SRC}" branch --list)" "$(printf '* main')" "r2: source repo checkout untouched"
assert_eq "$(git -C "${SRC}" worktree list | wc -l | tr -d ' ')" "1" "r2: temporary worktree removed"
assert_eq "$(field newsig000000 state)" "measured" "r2: a harmful row with no trailer commit stays measured"
assert_eq "$(contains "$(field newsig000000 revert_error)" "no commit")" "yes" "r2: and records why the revert failed"
assert_eq "$(field ineff0000000 state)" "measured" "r2: an ineffective row is never reverted automatically"

# A second active run does not retry a failed revert every night without new evidence,
# and does not touch the reverted row.
: > "${GHLOG}"
bash "${AUTO_APPLY_SH}" >/dev/null 2>&1
assert_eq "$(grep -c 'pr create' "${GHLOG}")" "0" "r2: a second run opens no PR"

# --- r3: notice reports the automatic revert ------------------------------------
rm -f "${AH}/notice-sentinel"
notice="$(printf '{"cwd":"/tmp/project"}' | CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR="${TMP}/no-agents" CCGM_AUTOHEAL_REAL_HOME="${HOME}" CCGM_AUTOHEAL_NOW="${TODAY}T13:00:00+00:00" PATH="/usr/bin:/bin:$(dirname "$(command -v python3)")" python3 "${NOTICE}")"
msg="$(printf '%s' "${notice}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("systemMessage",""))')"
assert_eq "$(contains "${msg}" "reverted rm permission_denied: add a rule to git-workflow.md (failures rose 2.0 → 3.0 per 100 calls)")" "yes" "r3: notice reports the automatic revert"
assert_eq "$(contains "${msg}" "ineff0000000")" "no" "r3: an outcome already announced is not repeated"

# --- d1: redraft uncovers an ineffective fix's signature; revert refuses non-merged rows ---
REVIEW="${MODULE_ROOT}/bin/autoheal-review.py"
excluded_cp() {
    python3 "${AGG}" --date 2026-09-28 >/dev/null 2>&1
    python3 - "${AH}/signatures/2026-09-28.json" <<'PY'
import json, sys
for s in json.load(open(sys.argv[1]))["signatures"]:
    if s["cmd_head"] == "cp":
        print(s.get("excluded", "none"))
PY
}
assert_eq "$(excluded_cp)" "covered" "d1: a measured fix keeps its signature covered"
out="$(python3 "${REVIEW}" redraft ineff0000000)"
assert_eq "$(contains "${out}" '"ok": true')" "yes" "d1: redraft succeeds on a measured row"
assert_eq "$(field ineff0000000 state)" "measured" "d1: redraft keeps the row measured (the rule stays merged)"
assert_eq "$(excluded_cp)" "none" "d1: after redraft the aggregator may draft the signature again"
out="$(python3 "${REVIEW}" redraft recent000000)"; rc=$?
assert_eq "${rc}" "1" "d1: redraft refuses a row not yet measured"
out="$(python3 "${REVIEW}" revert issue0000000)"; rc=$?
assert_eq "${rc}" "1" "d1: revert refuses an issue fix"
assert_eq "$(contains "${out}" "no commit to revert")" "yes" "d1: and says why"
out="$(python3 "${REVIEW}" revert ready0000000)"; rc=$?
assert_eq "${rc}" "1" "d1: revert refuses a row that was never applied"

echo ""
echo "test-outcomes.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
