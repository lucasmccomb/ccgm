#!/usr/bin/env bash
# test-ledger.sh
#
# The single proposal ledger (#1099 Phase 3.1):
#   - lib/ledger.py: append, lookup by id over the whole file, state change,
#     per-day and ready views
#   - /autoheal-apply <id> finds a 30-day-old ledger row (apply-proposal.py)
#   - retention never deletes a ready row, and prunes only old dropped rows
#   - bin/autoheal-ledger-migrate.py: --dry-run plans 22 legacy rows and writes
#     nothing; --apply writes the ledger, retires the old directory, and a second
#     --apply adds nothing
#
# Run: bash modules/autoheal/tests/test-ledger.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPLY="${MODULE_ROOT}/lib/apply-proposal.py"
RETENTION="${MODULE_ROOT}/bin/autoheal-retention.sh"
MIGRATE="${MODULE_ROOT}/bin/autoheal-ledger-migrate.py"

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

TMP="$(mktemp -d -t autoheal-ledger.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

# py <ledger-file> <code>: python with ledger.py importable and the ledger pointed at the file.
py() {
    CCGM_AUTOHEAL_LEDGER="$1" PYTHONPATH="${MODULE_ROOT}/lib" python3 -c "$2"
}

# --- lib/ledger.py -------------------------------------------------------
L="${TMP}/a/proposals.jsonl"
mkdir -p "${TMP}/a"
out="$(py "${L}" '
import ledger
ledger.append_row({"id": "sig1", "signature_id": "sig1", "state": "dropped", "source_day": "2026-01-01"})
ledger.append_row({"id": "sig1", "signature_id": "sig1", "state": "ready", "source_day": "2026-01-20", "target": "t", "diff": "d"})
ledger.append_row({"id": "sig2", "signature_id": "sig2", "state": "skipped", "source_day": "2026-01-20"})
print(ledger.find("sig1")["state"])
print(ledger.find("sig2")["state"])
print(ledger.find("nope"))
print(len(ledger.rows_for_day("2026-01-20")))
print(ledger.set_state("sig1", "applied", applied_at="x"))
print(ledger.find("sig1")["state"], ledger.find("sig1")["applied_at"])
print(ledger.set_state("sig1", "rejected"))
print([r["state"] for r in ledger.read_rows()])
' | tr '\n' ' ')"
assert_eq "${out}" "ready skipped None 2 True applied x False ['dropped', 'applied', 'skipped'] " "t1: find prefers the open row; set_state moves it; the dropped row is untouched"

# --- ready view ------------------------------------------------------------
L="${TMP}/b/proposals.jsonl"
mkdir -p "${TMP}/b"
out="$(py "${L}" '
import ledger
ledger.append_row({"id": "r", "state": "ready"})
ledger.append_row({"id": "s_open", "state": "snoozed", "snoozed_until": "2000-01-01T00:00:00Z"})
ledger.append_row({"id": "s_shut", "state": "snoozed", "snoozed_until": "2999-01-01T00:00:00Z"})
ledger.append_row({"id": "l", "state": "legacy"})
print(sorted(r["id"] for r in ledger.ready_rows()))
')"
assert_eq "${out}" "['r', 's_open']" "t2: ready view = ready rows + expired snoozes; legacy never"

# --- /autoheal-apply <id> sees a 30-day-old row ---------------------------
L="${TMP}/c/proposals.jsonl"
mkdir -p "${TMP}/c"
python3 - "${L}" <<'PY'
import json, sys, datetime as dt
old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
open(sys.argv[1], "w").write(json.dumps({"id": "old1", "signature_id": "old1", "state": "ready", "kind": "rule_insert",
    "target": "modules/x/rules/x.md", "diff": "D", "generated_at": old}) + "\n")
PY
out="$(CCGM_AUTOHEAL_LEDGER="${L}" python3 - "${APPLY}" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ap", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
row = m._find_proposal("old1")
print(row["id"] if row else None, row["target"] if row else None)
PY
)"
assert_eq "${out}" "old1 modules/x/rules/x.md" "t3: apply-proposal finds a 30-day-old ledger row"

# --- retention -------------------------------------------------------------
AH="${TMP}/d"
mkdir -p "${AH}"
python3 - "${AH}/proposals.jsonl" <<'PY'
import json, sys, datetime as dt
def ago(n): return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).isoformat()
rows = [
  {"id": "ready_old", "state": "ready", "generated_at": ago(200)},
  {"id": "snoozed_old", "state": "snoozed", "generated_at": ago(200)},
  {"id": "applied_old", "state": "applied", "generated_at": ago(200)},
  {"id": "skipped_old", "state": "skipped", "generated_at": ago(200)},
  {"id": "dropped_old", "state": "dropped", "generated_at": ago(200)},
  {"id": "dropped_new", "state": "dropped", "generated_at": ago(3)},
]
open(sys.argv[1], "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY
touch -t 202001010000 "${AH}/proposals.jsonl"
CCGM_AUTOHEAL_DIR="${AH}" bash "${RETENTION}" >/dev/null 2>&1
out="$(python3 -c "
import json, sys
print(' '.join(json.loads(l)['id'] for l in open(sys.argv[1])))" "${AH}/proposals.jsonl")"
assert_eq "${out}" "ready_old snoozed_old applied_old skipped_old dropped_new" "t4: retention keeps ready/snoozed/applied/skipped rows (any age) and recent dropped; prunes old dropped"
assert_eq "$([ -f "${AH}/proposals.jsonl" ] && echo present)" "present" "t4b: the ledger file is not gzipped away by age"

# --- migration -------------------------------------------------------------
M="${TMP}/m"
mkdir -p "${M}/proposals"
python3 - "${M}/proposals" <<'PY'
import json, sys, gzip, os
d = sys.argv[1]
n = 0
for day in range(1, 8):
    rows = []
    for k in range(3 if day < 7 else 4):
        n += 1
        rows.append({"id": f"prop_{n}", "kind": "settings_allow_add", "title": f"t{n}", "fingerprint": f"fp{n}",
                     "proposed_diff_target": "modules/settings/x", "proposed_diff": "+x",
                     "generated_at": f"2026-05-{day:02d}T08:00:00Z"})
    data = "".join(json.dumps(r) + "\n" for r in rows)
    if day == 1:   # a day retention already gzipped
        with gzip.open(os.path.join(d, f"2026-05-{day:02d}.jsonl.gz"), "wt") as fh: fh.write(data)
    else:
        open(os.path.join(d, f"2026-05-{day:02d}.jsonl"), "w").write(data)
# one post-redesign row keeps its state and sheds the duplicate fields
open(os.path.join(d, "2026-10-01.jsonl"), "w").write(json.dumps({"id": "sigA", "signature_id": "sigA", "state": "ready",
    "kind": "rule_insert", "target": "t", "diff": "D", "proposed_diff_target": "t", "proposed_diff": "D",
    "generated_at": "2026-10-01T08:00:00Z"}) + "\n")
assert n == 22, n
PY
dry="$(CCGM_AUTOHEAL_DIR="${M}" python3 "${MIGRATE}" 2>&1)"
assert_eq "$(printf '%s' "${dry}" | grep -c 'legacy: 22')" "1" "t5: --dry-run plans 22 legacy rows"
assert_eq "$([ -e "${M}/proposals.jsonl" ] && echo wrote || echo none)" "none" "t5b: --dry-run writes no ledger"
assert_eq "$([ -d "${M}/proposals" ] && echo kept)" "kept" "t5c: --dry-run leaves proposals/ alone"

CCGM_AUTOHEAL_DIR="${M}" python3 "${MIGRATE}" --apply >/dev/null 2>&1
rc=$?
assert_eq "${rc}" "0" "t6: --apply exits 0"
out="$(python3 -c "
import json, collections, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
print(len(rows), dict(sorted(collections.Counter(r['state'] for r in rows).items())))
sig = [r for r in rows if r['id'] == 'sigA'][0]
print('proposed_diff' in sig or 'proposed_diff_target' in sig, sig['target'], sig['diff'])
leg = [r for r in rows if r['state'] == 'legacy'][0]
print('proposed_diff' in leg, leg['target'], leg['diff'])
" "${M}/proposals.jsonl" | tr '\n' '|')"
assert_eq "${out}" "23 {'legacy': 22, 'ready': 1}|False t D|False modules/settings/x +x|" "t6b: 22 legacy + 1 ready row, duplicate fields gone"
assert_eq "$([ -d "${M}/proposals" ] && echo still || echo retired)" "retired" "t6c: the per-day directory is retired"
CCGM_AUTOHEAL_DIR="${M}" python3 "${MIGRATE}" --apply >/dev/null 2>&1
assert_eq "$(wc -l < "${M}/proposals.jsonl" | tr -d ' ')" "23" "t7: a second --apply adds nothing"

echo ""
echo "test-ledger.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
