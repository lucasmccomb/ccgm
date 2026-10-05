#!/usr/bin/env bash
# test-autoheal-review.sh
#
# /autoheal-review (#1099 Phase 3.2): bin/autoheal-review.py builds the
# AskUserQuestion payloads and runs apply, reject and snooze. Everything runs
# against a fixture source repo with a bare fixture origin and a fake `gh` on
# PATH; nothing touches GitHub.
#
#   t1  payload: passes the ask-context gate's checker, carries its own evidence
#   t2  list: oldest first, at most 5
#   t3  apply rule_insert: worktree -> branch -> commit with trailers -> push ->
#       PR -> merge; ledger row applied with baseline_rate; source repo untouched
#   t4  merge refused: row stays ready with apply_error, PR kept; retry merges
#       without opening a second PR; failing checks; behind branch
#   t5  edit then apply: replacement text re-validated and used; bad edits refused
#   t6  validation failure stops before any git or gh call
#   t7  issue proposal: gh issue create, row applied with the URL
#   t8  reject: suppressed 90 days; snooze: 14 days; aggregator honours both
#   t9  apply refuses a row that is not ready
#
# Run: bash modules/autoheal/tests/test-autoheal-review.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
REVIEW="${MODULE_ROOT}/bin/autoheal-review.py"
GATE="${REPO_ROOT}/modules/ask-context/hooks/ask-context-gate.py"
AGG="${MODULE_ROOT}/bin/autoheal-aggregate.py"

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

TMP="$(mktemp -d -t autoheal-review.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

export GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid
export GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export HOME="${TMP}/home"
mkdir -p "${HOME}"

# --- fixture source repo + bare origin -------------------------------------
ORIGIN="${TMP}/origin.git"
SRC="${TMP}/src"
git init -q --bare -b main "${ORIGIN}"
git init -q -b main "${SRC}"
mkdir -p "${SRC}/modules/git-workflow/rules" "${SRC}/tests"
touch "${SRC}/start.sh"
printf '# Git Workflow\n\n## Shell Quoting\n\nKeep commands simple.\n\n## Branches\n\nBranch first.\n' \
    > "${SRC}/modules/git-workflow/rules/git-workflow.md"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-no-personal-data.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "${SRC}/tests/test-modules.sh"
git -C "${SRC}" add -A
git -C "${SRC}" commit -q -m "fixture"
git -C "${SRC}" remote add origin "${ORIGIN}"
git -C "${SRC}" push -q origin main
git -C "${SRC}" fetch -q origin
git -C "${SRC}" branch -q --set-upstream-to=origin/main main

# --- fake gh ---------------------------------------------------------------
BIN="${TMP}/bin"
mkdir -p "${BIN}"
GHLOG="${TMP}/gh.log"
cat > "${BIN}/gh" <<'GH'
#!/usr/bin/env bash
printf '%s' "$*" | tr '\n' ' ' >> "${GHLOG}"
printf '\n' >> "${GHLOG}"
case "$1 $2" in
    "pr create")
        # Snapshot the pushed branch: a successful apply deletes it from origin afterward.
        while [ $# -gt 0 ]; do
            [ "$1" = "--head" ] && head="$2"
            shift
        done
        git -C "${FAKE_ORIGIN}" update-ref "refs/snapshots/${head#autoheal/}" "refs/heads/${head}"
        echo "https://github.com/fixture/ccgm/pull/7" ;;
    "pr checks") echo "all checks were successful"; exit "${FAKE_GH_CHECKS_RC:-0}" ;;
    "pr merge")
        if [ -n "${FAKE_GH_MERGE_FAIL:-}" ]; then
            echo "Pull request is not mergeable: the base branch policy prohibits the merge" >&2
            exit 1
        fi
        if [ -n "${FAKE_GH_BEHIND:-}" ] && [ ! -e "${FAKE_GH_BEHIND}" ]; then
            touch "${FAKE_GH_BEHIND}"
            echo "Pull request is not mergeable: the head branch is not up to date with the base branch" >&2
            exit 1
        fi
        echo "merged" ;;
    "pr view") echo "0123456789abcdef0123456789abcdef01234567" ;;
    "pr update-branch") echo "updated" ;;
    "issue create") echo "https://github.com/fixture/ccgm/issues/9" ;;
    *) echo "fake gh: unexpected $*" >&2; exit 64 ;;
esac
GH
chmod +x "${BIN}/gh"
export GHLOG FAKE_ORIGIN="${ORIGIN}"
export PATH="${BIN}:${PATH}"

# --- autoheal data dir -----------------------------------------------------
AH="${TMP}/ah"
mkdir -p "${AH}/events" "${AH}/counts"
printf '{"ccgm_repo_path": "%s"}\n' "${SRC}" > "${AH}/config.json"
export CCGM_AUTOHEAL_DIR="${AH}"
export CCGM_AUTOHEAL_CONFIG="${AH}/config.json"
export SRC

# py <code>: python with the module libs importable.
py() { PYTHONPATH="${MODULE_ROOT}/lib" python3 -c "$1"; }

# seed: writes the ledger and the baseline events. MANY, ISSUE, BADANCHOR pick the rows.
seed() {
    rm -f "${AH}"/events/*.jsonl "${AH}"/counts/*.json "${AH}"/proposals.jsonl "${TMP}/behind"
    : > "${GHLOG}"
    py '
import datetime as dt, json, os
import draft_proposals as dp
src = os.environ["SRC"]; ah = os.environ["CCGM_AUTOHEAL_DIR"]
target = "modules/git-workflow/rules/git-workflow.md"
old = open(os.path.join(src, target)).read()
new = dp.insert_under_heading(old, "Shell Quoting", ["- Quote any argument that holds `==` or `*` in zsh."])
diff = dp.unified_diff(target, old, new)
today = dt.date.today()
def row(i, days_old, **kw):
    r = {"id": i, "signature_id": i, "state": "ready", "kind": "rule_insert", "tool_name": "Bash",
         "cmd_head": "echo", "error_class": "zsh_no_match", "occurrence_count": 12,
         "evidence": {"count": 12, "sessions": 4, "repos": 2, "days": 5,
                      "first_seen": "2026-09-01", "last_seen": "2026-09-12", "calls": 900,
                      "rate_per_100_calls": 1.3,
                      "samples": ["zsh: no matches found: ==", "zsh: no matches found: *.log", "third sample"]},
         "title": "echo zsh_no_match: add a rule to git-workflow.md", "target": target,
         "anchor": "Shell Quoting", "insert_markdown": "- Quote any argument that holds `==` or `*` in zsh.",
         "diff": diff,
         "generated_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_old)).isoformat()}
    r.update(kw)
    return r
rows = [row("aaaaaaaaaaaa", 0)]
if os.environ.get("MANY"):
    rows = [row("id%09d" % n, 10 - n) for n in range(7)]
if os.environ.get("ISSUE"):
    rows = [row("bbbbbbbbbbbb", 0, kind="issue", target=None, anchor=None, diff=None, insert_markdown=None,
                module="hooks", issue_title="hooks: recurring hook denial (x)", issue_body="Evidence body.",
                title="hooks: denial recurs (x)", error_class="hook_denial_x")]
if os.environ.get("BADANCHOR"):
    rows = [row("cccccccccccc", 0, anchor="No Such Heading")]
open(os.path.join(ah, "proposals.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
# Baseline: 2 echo/zsh_no_match failures in the 14 days before today, 100 Bash calls -> 2.0 per 100.
for off in (3, 5):
    d = (today - dt.timedelta(days=off)).isoformat()
    open(os.path.join(ah, "events", d + ".jsonl"), "w").write(json.dumps(
        {"kind": "tool_failure", "tool_name": "Bash", "cmd_head": "echo", "error_class": "zsh_no_match",
         "session_id": "s%d" % off}) + "\n")
d = (today - dt.timedelta(days=4)).isoformat()
open(os.path.join(ah, "counts", d + ".json"), "w").write(json.dumps({"Bash": 100}))
'
}

review() { python3 "${REVIEW}" "$@"; }
jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
row_of() { py "import ledger,json; print(json.dumps(ledger.find('$1')))"; }
src_state() { printf '%s|%s|%s' "$(git -C "${SRC}" status --porcelain)" "$(git -C "${SRC}" worktree list)" "$(git -C "${SRC}" branch --list)"; }
contains() { case "$1" in *"$2"*) echo yes ;; *) echo no ;; esac; }

# --- t1: payload passes the gate checker -----------------------------------
seed
out="$(review list)"
echo "${out}" > "${TMP}/list.json"
assert_eq "$(echo "${out}" | jget 'len(d["items"])')" "1" "t1: one ready row gives one item"
res="$(GATE="${GATE}" python3 - "${TMP}/list.json" <<'PY'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("gate", os.environ["GATE"])
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
item = json.load(open(sys.argv[1]))["items"][0]
problems = []
for name in ("question", "edit_question", "reject_question"):
    payload = item[name]
    try:
        gate.gate_deictic(payload)
    except SystemExit:
        problems.append(name + ": deictic")
    chars = gate.payload_context_chars(payload)
    if chars < 200:
        problems.append(f"{name}: only {chars} context chars")
q = item["question"]["questions"][0]
text = q["question"]
for needle in ("Bash", "echo", "zsh_no_match", "12", "4 sessions", "2026-09-01", "2026-09-12",
               "zsh: no matches found: ==", "zsh: no matches found: *.log",
               "modules/git-workflow/rules/git-workflow.md", "Shell Quoting"):
    if needle not in text:
        problems.append("question lacks " + needle)
if "third sample" in text:
    problems.append("more than 2 samples shown")
labels = [o["label"] for o in q["options"]]
if labels != ["Apply", "Edit then apply", "Reject", "Snooze 14d"]:
    problems.append("labels " + repr(labels))
if "+- Quote any argument" not in q["options"][0].get("preview", ""):
    problems.append("Apply preview lacks the diff")
desc = {o["label"]: o["description"] for o in q["options"]}
for label, text_ in desc.items():
    if len(text_) < 20:
        problems.append("thin description on " + label)
if "squash" not in desc["Apply"]:
    problems.append("Apply description lacks the consequence")
if "suppressed until" not in desc["Reject"]:
    problems.append("Reject description lacks the date")
if "until" not in desc["Snooze 14d"]:
    problems.append("Snooze description lacks the date")
if q.get("multiSelect") is not False:
    problems.append("multiSelect")
if len(q.get("header", "")) > 12:
    problems.append("header too long")
print("ok" if not problems else "; ".join(problems))
PY
)"
assert_eq "${res}" "ok" "t1: payload passes the ask-context checks and carries its evidence"

# --- t2: oldest first, at most 5 ---------------------------------------------
MANY=1 seed
out="$(review list)"
assert_eq "$(echo "${out}" | jget '[i["id"] for i in d["items"]]')" "['id000000000', 'id000000001', 'id000000002', 'id000000003', 'id000000004']" "t2: oldest five, oldest first"
assert_eq "$(echo "${out}" | jget 'd["total_ready"]')" "7" "t2: total_ready counts every ready row"

# --- t3: apply happy path -----------------------------------------------------
seed
before="$(src_state)"
out="$(review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "0" "t3: apply exits 0"
assert_eq "$(echo "${out}" | jget 'd["ok"]')" "True" "t3: result ok"
assert_eq "$(echo "${out}" | jget 'd["pr_url"]')" "https://github.com/fixture/ccgm/pull/7" "t3: PR url reported"
row="$(row_of aaaaaaaaaaaa)"
assert_eq "$(echo "${row}" | jget 'd["state"]')" "applied" "t3: ledger row applied"
assert_eq "$(echo "${row}" | jget 'd["pr_url"]')" "https://github.com/fixture/ccgm/pull/7" "t3: row stores the PR url"
assert_eq "$(echo "${row}" | jget 'd["merge_sha"]')" "0123456789abcdef0123456789abcdef01234567" "t3: row stores the merge sha"
assert_eq "$(echo "${row}" | jget 'd["baseline_rate"]')" "2.0" "t3: baseline_rate from the 14 days before"
assert_eq "$(echo "${row}" | jget 'bool(d["merged_at"])')" "True" "t3: merged_at recorded"
assert_eq "$(git -C "${ORIGIN}" log refs/snapshots/aaaaaaaaaaaa -1 --format=%s)" "#auto: apply autoheal proposal aaaaaaaaaaaa" "t3: commit subject follows the #auto convention"
msg="$(git -C "${ORIGIN}" log refs/snapshots/aaaaaaaaaaaa -1 --format=%B)"
assert_eq "$(contains "${msg}" "Autoheal-Id: aaaaaaaaaaaa")" "yes" "t3: commit trailer Autoheal-Id"
assert_eq "$(contains "${msg}" "Autoheal-Signature: Bash|echo|zsh_no_match")" "yes" "t3: commit trailer Autoheal-Signature"
assert_eq "$(git -C "${ORIGIN}" show refs/snapshots/aaaaaaaaaaaa:modules/git-workflow/rules/git-workflow.md | grep -c 'Quote any argument')" "1" "t3: pushed branch holds the rule"
assert_eq "$(git -C "${ORIGIN}" rev-parse main)" "$(git -C "${SRC}" rev-parse origin/main)" "t3: origin main untouched by the push"
log="$(cat "${GHLOG}")"
assert_eq "$(echo "${log}" | grep -c '^pr create')" "1" "t3: one gh pr create"
assert_eq "$(echo "${log}" | grep -c '^pr merge.*--squash')" "1" "t3: gh pr merge --squash"
assert_eq "$(echo "${log}" | grep -c -- '--admin')" "0" "t3: never --admin"
assert_eq "$(echo "${log}" | grep '^pr merge' | grep -c 'Autoheal-Id: aaaaaaaaaaaa')" "1" "t3: squash body carries the trailer"
assert_eq "$(git -C "${ORIGIN}" branch --list 'autoheal/aaaaaaaaaaaa' | grep -c autoheal)" "0" "t3: the merged branch is deleted from origin"
assert_eq "$(src_state)" "${before}" "t3: source working tree, worktree list and branches unchanged"
assert_eq "$(git -C "${SRC}" worktree list | wc -l | tr -d ' ')" "1" "t3: no worktree left"

# --- t4: merge refused, then retry -------------------------------------------
seed
before="$(src_state)"
out="$(FAKE_GH_MERGE_FAIL=1 review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "1" "t4: refused merge exits 1"
assert_eq "$(echo "${out}" | jget 'd["ok"]')" "False" "t4: result not ok"
row="$(row_of aaaaaaaaaaaa)"
assert_eq "$(echo "${row}" | jget 'd["state"]')" "ready" "t4: row stays ready"
assert_eq "$(contains "$(echo "${row}" | jget 'd["apply_error"]')" "not mergeable")" "yes" "t4: apply_error records the refusal"
assert_eq "$(echo "${row}" | jget 'd["pr_url"]')" "https://github.com/fixture/ccgm/pull/7" "t4: PR url kept so the PR is not lost"
assert_eq "$(src_state)" "${before}" "t4: source repo unchanged after a failure"
assert_eq "$(git -C "${ORIGIN}" branch --list 'autoheal/aaaaaaaaaaaa' | grep -c autoheal)" "1" "t4: the branch stays on origin while the PR is open"
out="$(review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "0" "t4: retry merges"
assert_eq "$(git -C "${ORIGIN}" branch --list 'autoheal/aaaaaaaaaaaa' | grep -c autoheal)" "0" "t4: the retry's merge deletes the branch"
assert_eq "$(grep -c '^pr create' "${GHLOG}")" "1" "t4: retry opens no second PR"
assert_eq "$(row_of aaaaaaaaaaaa | jget 'd["state"]')" "applied" "t4: retry applies the row"

seed
out="$(FAKE_GH_CHECKS_RC=1 review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "1" "t4b: failing checks exit 1"
assert_eq "$(grep -c '^pr merge' "${GHLOG}")" "0" "t4b: no merge attempted when checks fail"
row="$(row_of aaaaaaaaaaaa)"
assert_eq "$(echo "${row}" | jget 'd["state"]')" "ready" "t4b: row ready after a CI failure"
assert_eq "$(contains "$(echo "${row}" | jget 'd["apply_error"]')" "checks")" "yes" "t4b: CI failure recorded"

seed
out="$(FAKE_GH_BEHIND="${TMP}/behind" review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "0" "t4c: a behind branch is updated and merged"
assert_eq "$(grep -c '^pr update-branch.*--rebase' "${GHLOG}")" "1" "t4c: gh pr update-branch --rebase"
assert_eq "$(grep -c '^pr merge' "${GHLOG}")" "2" "t4c: merge retried once"

# --- t5: edit then apply ------------------------------------------------------
seed
printf -- '- Use single quotes around `==` in zsh.\n' > "${TMP}/edit.md"
out="$(review apply aaaaaaaaaaaa --insert-file "${TMP}/edit.md")"; rc=$?
assert_eq "${rc}" "0" "t5: edited apply exits 0"
assert_eq "$(git -C "${ORIGIN}" show refs/snapshots/aaaaaaaaaaaa:modules/git-workflow/rules/git-workflow.md | grep -c 'single quotes')" "1" "t5: edited text is what was pushed"
assert_eq "$(git -C "${ORIGIN}" show refs/snapshots/aaaaaaaaaaaa:modules/git-workflow/rules/git-workflow.md | grep -c 'Quote any argument')" "0" "t5: the original text is not"
assert_eq "$(row_of aaaaaaaaaaaa | jget 'd["state"], d.get("edited")')" "applied True" "t5: row applied and marked edited"
seed
python3 -c "print('\n'.join('- line %d' % n for n in range(9)))" > "${TMP}/long.md"
out="$(review apply aaaaaaaaaaaa --insert-file "${TMP}/long.md")"; rc=$?
assert_eq "${rc}" "1" "t5b: a 9-line edit is refused"
assert_eq "$(wc -c < "${GHLOG}" | tr -d ' ')" "0" "t5b: refused edit makes no gh call"
assert_eq "$(row_of aaaaaaaaaaaa | jget 'd["state"]')" "ready" "t5b: row stays ready"
: > "${TMP}/empty.md"
out="$(review apply aaaaaaaaaaaa --insert-file "${TMP}/empty.md")"; rc=$?
assert_eq "${rc}" "1" "t5c: an empty edit is refused"

# --- t6: validation failure stops everything ----------------------------------
BADANCHOR=1 seed
before="$(src_state)"
out="$(review apply cccccccccccc)"; rc=$?
assert_eq "${rc}" "1" "t6: failing validate exits 1"
assert_eq "$(contains "$(echo "${out}" | jget 'd["error"]')" "anchor_missing")" "yes" "t6: the validate reason is reported"
assert_eq "$(wc -c < "${GHLOG}" | tr -d ' ')" "0" "t6: no gh call"
assert_eq "$(git -C "${ORIGIN}" branch --list 'autoheal/cccccccccccc' | grep -c autoheal)" "0" "t6: nothing pushed"
assert_eq "$(src_state)" "${before}" "t6: source repo unchanged"

# --- t7: issue proposal -------------------------------------------------------
ISSUE=1 seed
out="$(review apply bbbbbbbbbbbb)"; rc=$?
assert_eq "${rc}" "0" "t7: issue apply exits 0"
assert_eq "$(grep -c '^issue create' "${GHLOG}")" "1" "t7: gh issue create called"
assert_eq "$(grep '^issue create' "${GHLOG}" | grep -c -- '--label')" "0" "t7: no labels requested"
assert_eq "$(grep '^issue create' "${GHLOG}" | grep -c 'Evidence body')" "1" "t7: issue body carries the evidence"
assert_eq "$(row_of bbbbbbbbbbbb | jget 'd["state"], d["issue_url"]')" "applied https://github.com/fixture/ccgm/issues/9" "t7: row applied with the issue URL"
ISSUE=1 seed
out="$(review list)"
assert_eq "$(echo "${out}" | jget '"denial" in d["items"][0]["question"]["questions"][0]["question"].lower()')" "True" "t7b: issue payload names the denial"
assert_eq "$(echo "${out}" | jget '"Evidence body" in d["items"][0]["question"]["questions"][0]["options"][0]["preview"]')" "True" "t7b: issue preview holds the issue body"
assert_eq "$(echo "${out}" | jget '[o["label"] for o in d["items"][0]["question"]["questions"][0]["options"]]')" "['Apply', 'Reject', 'Snooze 14d']" "t7b: an issue has no Edit option"

# --- t8: reject and snooze ----------------------------------------------------
seed
out="$(review reject aaaaaaaaaaaa --reason "rule is too broad")"; rc=$?
assert_eq "${rc}" "0" "t8: reject exits 0"
res="$(py 'import ledger,datetime as dt; r=ledger.find("aaaaaaaaaaaa"); u=dt.datetime.fromisoformat(r["suppressed_until"]); n=dt.datetime.now(dt.timezone.utc); print(r["state"], r["reject_reason"], (u-n).days)')"
assert_eq "${res}" "rejected rule is too broad 89" "t8: rejected, reason kept, suppressed for 90 days"
assert_eq "$(review list | jget 'len(d["items"])')" "0" "t8: rejected row leaves the review list"
res="$(AGG="${AGG}" py '
import importlib.util, os, datetime as dt
spec = importlib.util.spec_from_file_location("agg", os.environ["AGG"])
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)
d = os.environ["CCGM_AUTOHEAL_DIR"]; today = dt.datetime.now(dt.timezone.utc).date()
print(*("aaaaaaaaaaaa" in agg._covered_ids(d, today + dt.timedelta(days=n)) for n in (0, 88, 91)))')"
assert_eq "${res}" "True True False" "t8: aggregator covers a rejected signature for 90 days, then lets it return"

seed
out="$(review snooze aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "0" "t8: snooze exits 0"
res="$(py 'import ledger,datetime as dt; r=ledger.find("aaaaaaaaaaaa"); u=dt.datetime.fromisoformat(r["snoozed_until"]); n=dt.datetime.now(dt.timezone.utc); print(r["state"], (u-n).days)')"
assert_eq "${res}" "snoozed 13" "t8: snoozed for 14 days"
assert_eq "$(review list | jget 'len(d["items"])')" "0" "t8: snoozed row leaves the review list"
later="$(python3 -c "import datetime as dt; print((dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=15)).isoformat())")"
assert_eq "$(review list --now "${later}" | jget 'len(d["items"])')" "1" "t8: it returns after 14 days"
res="$(AGG="${AGG}" py '
import importlib.util, os, datetime as dt
spec = importlib.util.spec_from_file_location("agg", os.environ["AGG"])
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)
print("aaaaaaaaaaaa" in agg._covered_ids(os.environ["CCGM_AUTOHEAL_DIR"], dt.datetime.now(dt.timezone.utc).date()))')"
assert_eq "${res}" "True" "t8: aggregator excludes a snoozed signature"

# --- t9: apply refuses a row that is not ready --------------------------------
seed
review reject aaaaaaaaaaaa --reason x >/dev/null
out="$(review apply aaaaaaaaaaaa)"; rc=$?
assert_eq "${rc}" "1" "t9: apply refuses a rejected row"
assert_eq "$(wc -c < "${GHLOG}" | tr -d ' ')" "0" "t9: and calls nothing"

echo ""
echo "test-autoheal-review.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
