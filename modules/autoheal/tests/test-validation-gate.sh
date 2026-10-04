#!/usr/bin/env bash
# Tests for the validation gate (#1099 Phase 2.3): validate() in
# lib/apply-proposal.py and its wiring into lib/draft_proposals.py.
#
# A fixture git repo shaped like CCGM stands in for the source repo. Its
# tests/test-no-personal-data.sh is the real script; tests/test-modules.sh is a
# stub that fails when a module file holds BREAK_MODULES and sleeps when one
# holds SLOW_MODULES. origin/main is a local ref (no remote needed).
#
# Cases: clean pass; personal_data; module_tests; path_not_candidate;
# rule_budget (rolling 7 days, applied plus ready, path-scoped rules exempt,
# boundary of exactly N passes); apply_conflict; anchor_missing;
# validation_unavailable (no repo, timeout); the source repo is untouched
# (status, HEAD, refs, worktree list, no leftover temp dirs); draft finish
# stores a failing row as dropped with its reason; apply refuses a failing or
# dropped row before touching the clone.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
ROOT=$(mktemp -d -t autoheal_gate.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

export TMPDIR="${ROOT}/tmp"
mkdir -p "${TMPDIR}"
export CCGM_AUTOHEAL_DIR="${ROOT}/state"
export CCGM_AUTOHEAL_CONFIG="${ROOT}/config.json"
export CCGM_AUTOHEAL_PROPOSALS_DIR="${ROOT}/proposals"
export CCGM_AUTOHEAL_APPLIED_DIR="${ROOT}/applied"
mkdir -p "${CCGM_AUTOHEAL_DIR}" "${CCGM_AUTOHEAL_PROPOSALS_DIR}" "${CCGM_AUTOHEAL_APPLIED_DIR}"

REPO="${ROOT}/repo"
GITC=(git -C "${REPO}" -c core.hooksPath=/dev/null -c user.name=fx -c user.email=fx@example.com)
mkdir -p "${REPO}/modules/alpha/rules" "${REPO}/modules/beta/rules" "${REPO}/tests"
git -C "${REPO}" init -q -b main
printf '#!/usr/bin/env bash\n' > "${REPO}/start.sh"
cat > "${REPO}/modules/alpha/rules/alpha.md" <<'EOF'
# Alpha

## Section A

- first
- second

## Section B

text
EOF
cat > "${REPO}/modules/beta/rules/beta.md" <<'EOF'
---
paths: "**/*.ts"
---

# Beta

## Section A

- one
EOF
cp "${REPO_ROOT}/tests/test-no-personal-data.sh" "${REPO}/tests/test-no-personal-data.sh"
cat > "${REPO}/tests/test-modules.sh" <<'EOF'
#!/usr/bin/env bash
grep -rq SLOW_MODULES modules && sleep 8
grep -rq BREAK_MODULES modules && { echo "module check failed"; exit 1; }
exit 0
EOF
"${GITC[@]}" add -A
"${GITC[@]}" commit -q -m "fixture"
git -C "${REPO}" update-ref refs/remotes/origin/main HEAD
printf '{"ccgm_repo_path": "%s"}\n' "${REPO}" > "${CCGM_AUTOHEAL_CONFIG}"

snapshot() {
    {
        git -C "${REPO}" status --porcelain --ignored
        git -C "${REPO}" rev-parse HEAD
        git -C "${REPO}" for-each-ref
        git -C "${REPO}" worktree list
        git -C "${REPO}" branch --list
    } | sed "s#${ROOT}#ROOT#g"
}
# py <script>: run a Python snippet with the two modules loaded as ap and dp.
py() {
    python3 - "${MODULE_ROOT}/lib" "${REPO}" <<PY
import importlib.util, json, os, sys, datetime as dt
LIB, REPO = sys.argv[1], sys.argv[2]
def load(f, n):
    s = importlib.util.spec_from_file_location(n, os.path.join(LIB, f))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ap = load("apply-proposal.py", "ap"); dp = load("draft_proposals.py", "dp")
NOW = dt.datetime.now(dt.timezone.utc)
def row(target, anchor, lines, **kw):
    old = open(os.path.join(REPO, target), encoding="utf-8").read()
    new = dp.insert_under_heading(old, anchor, lines)
    diff = dp.unified_diff(target, old, new)
    r = {"id": kw.pop("id", "p1"), "kind": "rule_insert", "state": "ready", "target": target,
         "anchor": anchor, "insert_markdown": "\n".join(lines), "diff": diff,
         "proposed_diff": diff, "proposed_diff_target": target,
         "generated_at": NOW.isoformat()}
    r.update(kw); return r
def show(label, res): print(label + "\t" + str(res[0]) + "\t" + res[1])
$1
PY
}

run_case() { py "$1" | grep "^$2	" | cut -f2-; }

# 1. A clean insert passes every check.
OUT="$(py '
show("clean", ap.validate(row("modules/alpha/rules/alpha.md", "Section A", ["- third"])))
')"
assert_contains "${OUT}" "clean	True	" "clean rule_insert passes all checks"

# 2. A secret-shaped string (built at runtime) is dropped as personal_data.
OUT="$(py '
tok = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
show("pd", ap.validate(row("modules/alpha/rules/alpha.md", "Section A", ["- use " + tok])))
')"
assert_contains "${OUT}" "pd	False	personal_data" "secret shape is dropped as personal_data"

# 3. A change that breaks the module checks.
OUT="$(py '
show("mt", ap.validate(row("modules/alpha/rules/alpha.md", "Section A", ["- BREAK_MODULES"])))
')"
assert_contains "${OUT}" "mt	False	module_tests" "failing test-modules.sh is dropped as module_tests"

# 4. A target that is not a rule file in origin/main.
OUT="$(py '
r = row("modules/alpha/rules/alpha.md", "Section A", ["- x"])
r["target"] = "modules/alpha/rules/missing.md"
show("pnc", ap.validate(r))
r["target"] = "tests/test-modules.sh"
show("pnc2", ap.validate(r))
')"
assert_contains "${OUT}" "pnc	False	path_not_candidate" "missing rule file is dropped as path_not_candidate"
assert_contains "${OUT}" "pnc2	False	path_not_candidate" "a non-rule file is dropped as path_not_candidate"

# 5. Rule budget: 20 lines per rolling 7 days across ready and applied rows.
mkdir -p "${CCGM_AUTOHEAL_PROPOSALS_DIR}" "${CCGM_AUTOHEAL_APPLIED_DIR}"
OUT="$(py '
def lines(n): return ["- budget line %d" % i for i in range(n)]
def put(name, rows):
    with open(os.path.join(os.environ["CCGM_AUTOHEAL_PROPOSALS_DIR"], name), "w") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
old = (NOW - dt.timedelta(days=10)).isoformat()
two = (NOW - dt.timedelta(days=2)).isoformat()
alpha = "modules/alpha/rules/alpha.md"
# 12 ready lines now, an old ready row (ignored), a 10-day-old row applied 2 days ago (8 lines).
put("a.jsonl", [row(alpha, "Section A", lines(12), id="r1"),
                row(alpha, "Section A", lines(8), id="old", generated_at=old),
                row(alpha, "Section A", lines(8), id="app", generated_at=old, state="applied")])
show("b_exact", ap.validate(row(alpha, "Section A", lines(8), id="new")))
os.makedirs(os.environ["CCGM_AUTOHEAL_APPLIED_DIR"], exist_ok=True)
with open(os.path.join(os.environ["CCGM_AUTOHEAL_APPLIED_DIR"], "x.jsonl"), "w") as fh:
    fh.write(json.dumps({"proposal_id": "app", "ts": two}) + "\n")
show("b_over", ap.validate(row(alpha, "Section A", lines(1), id="new")))
show("b_over25", ap.validate(row(alpha, "Section A", lines(5), id="new")))
show("b_self", ap.validate(row(alpha, "Section A", lines(8), id="r1")))
show("b_scoped", ap.validate(row("modules/beta/rules/beta.md", "Section A", lines(8), id="new")))
cfg = json.load(open(os.environ["CCGM_AUTOHEAL_CONFIG"])); cfg["rule_budget_lines_per_week"] = 40
json.dump(cfg, open(os.environ["CCGM_AUTOHEAL_CONFIG"], "w"))
show("b_cfg", ap.validate(row(alpha, "Section A", lines(8), id="new")))
cfg.pop("rule_budget_lines_per_week"); json.dump(cfg, open(os.environ["CCGM_AUTOHEAL_CONFIG"], "w"))
')"
assert_contains "${OUT}" "b_exact	True	" "12 ready + 8 new = 20 lines is within the budget (old and unapplied-old rows ignored)"
assert_contains "${OUT}" "b_over	False	rule_budget" "ready 12 + applied 8 + 1 new exceeds 20"
assert_contains "${OUT}" "b_over25	False	rule_budget" "25 lines inside a week is dropped as rule_budget"
assert_contains "${OUT}" "b_self	True	" "a row does not count against itself"
assert_contains "${OUT}" "b_scoped	True	" "insertions into a paths-scoped rule file are not budgeted"
assert_contains "${OUT}" "b_cfg	True	" "rule_budget_lines_per_week overrides the default"
rm -f "${CCGM_AUTOHEAL_PROPOSALS_DIR}"/*.jsonl "${CCGM_AUTOHEAL_APPLIED_DIR}"/*.jsonl

# 6. Upstream drift. First a context line the diff relies on changes: the heading
#    survives but the diff no longer applies.
py 'print(json.dumps(row("modules/alpha/rules/alpha.md", "Section A", ["- third"])))' > "${ROOT}/stale-row.json"
printf '# Alpha\n\n## Section A\n\n- first\n- second CHANGED\n\n## Section B\n\ntext\n' > "${REPO}/modules/alpha/rules/alpha.md"
"${GITC[@]}" commit -q -am "upstream edit"
git -C "${REPO}" update-ref refs/remotes/origin/main HEAD
OUT="$(py '
r = json.load(open(os.path.join(os.path.dirname(os.environ["CCGM_AUTOHEAL_CONFIG"]), "stale-row.json")))
show("conflict", ap.validate(r))
')"
assert_contains "${OUT}" "conflict	False	apply_conflict" "diff against changed context is dropped as apply_conflict"

# 7. Then the anchor heading is removed upstream.
printf '# Alpha\n\n## Section B\n\ntext\n' > "${REPO}/modules/alpha/rules/alpha.md"
"${GITC[@]}" commit -q -am "upstream removes the anchor"
git -C "${REPO}" update-ref refs/remotes/origin/main HEAD
OUT="$(py '
r = json.load(open(os.path.join(os.path.dirname(os.environ["CCGM_AUTOHEAL_CONFIG"]), "stale-row.json")))
show("anchor", ap.validate(r))
')"
assert_contains "${OUT}" "anchor	False	anchor_missing" "anchor removed upstream is dropped as anchor_missing"

# 8. Gate skips, never crashes, when it cannot run.
OUT="$(py '
cfg_path = os.environ["CCGM_AUTOHEAL_CONFIG"]
good = open(cfg_path).read()
open(cfg_path, "w").write(json.dumps({"ccgm_repo_path": "/nonexistent/ccgm"}))
show("norepo", ap.validate(row("modules/beta/rules/beta.md", "Section A", ["- x"])))
open(cfg_path, "w").write(good)
open(cfg_path, "w").write(json.dumps({"ccgm_repo_path": REPO, "validation_timeout_seconds": 1}))
show("slow", ap.validate(row("modules/beta/rules/beta.md", "Section A", ["- SLOW_MODULES"])))
open(cfg_path, "w").write(good)
')"
assert_contains "${OUT}" "norepo	False	validation_unavailable" "unresolvable source repo gives validation_unavailable"
assert_contains "${OUT}" "slow	False	validation_unavailable" "a check over its timeout gives validation_unavailable"

# 9. Non-diff rows (issue proposals) need no checks.
OUT="$(py 'show("issue", ap.validate({"id": "i1", "kind": "issue", "state": "ready"}))')"
assert_contains "${OUT}" "issue	True	" "an issue row passes without checks"

# 10. Validation leaves the source repo exactly as it was, passing or failing,
#     and removes its temp dirs.
BEFORE="$(snapshot)"
py '
tok = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
show("x", ap.validate(row("modules/beta/rules/beta.md", "Section A", ["- ok"])))
show("x", ap.validate(row("modules/beta/rules/beta.md", "Section A", ["- " + tok])))
show("x", ap.validate(row("modules/beta/rules/beta.md", "Section A", ["- BREAK_MODULES"])))
' > /dev/null
AFTER="$(snapshot)"
assert_eq "${AFTER}" "${BEFORE}" "source repo status, HEAD, refs, branches and worktrees unchanged"
assert_eq "$(find "${TMPDIR}" -mindepth 1 | wc -l | tr -d ' ')" "0" "no temp directories left behind"

# 11. Drafting: `finish` stores a failing row as dropped with its reason, a clean
#     one as ready.
export CCGM_AUTOHEAL_TODAY="2026-10-04"
DAY_FILE="${CCGM_AUTOHEAL_PROPOSALS_DIR}/${CCGM_AUTOHEAL_TODAY}.jsonl"
py '
tok = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
sig = {"signature_id": "sig000000001", "tool_name": "Bash", "cmd_head": "zsh", "error_class": "zsh_not_found",
       "count": 6, "sessions": 3, "days": 2}
base = {"signature": sig, "candidates": ["modules/beta/rules/beta.md"], "repo_root": REPO, "model": "m"}
def answer(line):
    return {"proposal": {"kind": "rule_insert", "target_path": "modules/beta/rules/beta.md",
                         "anchor_heading": "Section A", "insert_markdown": line}}
d = os.path.dirname(os.environ["CCGM_AUTOHEAL_CONFIG"])
for name, sid, line in (("bad", "sig00000000b", "- use " + tok), ("good", "sig00000000g", "- fine")):
    json.dump(dict(base, signature_id=sid, signature=dict(sig, signature_id=sid)), open(d + "/" + name + ".meta.json", "w"))
    json.dump(answer(line), open(d + "/" + name + ".answer.json", "w"))
' > /dev/null
for name in bad good; do
    python3 "${MODULE_ROOT}/lib/draft_proposals.py" finish --meta "${ROOT}/${name}.meta.json" \
        --answer "${ROOT}/${name}.answer.json" --date "${CCGM_AUTOHEAL_TODAY}" \
        --rejected-log "${ROOT}/rejected.log" > "${ROOT}/${name}.out"
done
assert_eq "$(json_get "${ROOT}/bad.out" "d['outcome'] + ':' + d['reason']")" "dropped:personal_data" "finish reports the drop and its reason"
assert_eq "$(json_get "${ROOT}/good.out" "d['outcome']")" "rule_insert" "finish reports a clean row as rule_insert"
ROWS="$(python3 -c "
import json,sys
for l in open(sys.argv[1]):
    r = json.loads(l); print(r['signature_id'], r['state'], r.get('drop_reason', ''))
" "${DAY_FILE}")"
assert_contains "${ROWS}" "sig00000000b dropped personal_data" "failing row is stored as dropped with drop_reason"
assert_contains "${ROWS}" "sig00000000g ready" "clean row is stored as ready"
assert_contains "$(cat "${ROOT}/rejected.log")" "personal_data" "the rejection log records the reason"
DIGEST_VISIBLE="$(python3 -c "
import json,sys
print(sum(1 for l in open(sys.argv[1]) if json.loads(l).get('state', 'ready') == 'ready'))
" "${DAY_FILE}")"
assert_eq "${DIGEST_VISIBLE}" "1" "only the ready row passes the digest's state filter"

# 12. Apply refuses a dropped row, and a ready row that fails the gate, before
#     it creates a branch.
BRANCHES="$(git -C "${REPO}" branch --list)"
OUT="$(CCGM_CLONE_ROOT="${REPO}" py '
tok = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
d = os.environ["CCGM_AUTOHEAL_PROPOSALS_DIR"]
with open(d + "/2026-10-04.jsonl", "a") as fh:
    fh.write(json.dumps(row("modules/beta/rules/beta.md", "Section A", ["- " + tok], id="forged")) + "\n")
    fh.write(json.dumps(row("modules/beta/rules/beta.md", "Section A", ["- x"], id="dead", state="dropped")) + "\n")
for pid in ("forged", "dead"):
    r = ap.apply_proposal(pid)
    print(pid + "\t" + str(r["success"]) + "\t" + str(r["error"]))
')"
assert_contains "${OUT}" "forged	False	validation failed: personal_data" "apply refuses a ready row that fails the gate"
assert_contains "${OUT}" "dead	False	proposal dead is dropped, not ready" "apply refuses a dropped row"
assert_eq "$(git -C "${REPO}" branch --list)" "${BRANCHES}" "apply created no branch"

echo ""
echo "test-validation-gate.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
