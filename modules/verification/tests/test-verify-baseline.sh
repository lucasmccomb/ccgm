#!/usr/bin/env bash
# Tests for modules/verification/bin/ccgm-verify-baseline (issue #1074).
# Each case runs in a fresh temp git repo with fake checks.
set -u
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/ccgm-verify-baseline"
PASS=0; FAIL=0
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

newrepo() {
  R="$(mktemp -d "$TMP/repo.XXXXXX")"
  git -C "$R" init -q
  cd "$R" || exit 1
}
run() { OUT="$(python3 "$SCRIPT" "$@" 2>&1)"; RC=$?; }
ok() {
  if [ "$1" = "$2" ]; then PASS=$((PASS+1)); echo "ok - $3"
  else FAIL=$((FAIL+1)); echo "not ok - $3 (expected '$2', got '$1')"; echo "$OUT" | sed 's/^/    /'; fi
}
has() {
  if printf '%s' "$OUT" | grep -qF -- "$1"; then PASS=$((PASS+1)); echo "ok - $2"
  else FAIL=$((FAIL+1)); echo "not ok - $2 (missing '$1')"; echo "$OUT" | sed 's/^/    /'; fi
}
hasnt() {
  if printf '%s' "$OUT" | grep -qF -- "$1"; then FAIL=$((FAIL+1)); echo "not ok - $2 (found '$1')"; echo "$OUT" | sed 's/^/    /'
  else PASS=$((PASS+1)); echo "ok - $2"; fi
}
baseline_file() { echo "$(git rev-parse --git-dir)/ccgm-verify-baseline.json"; }

# --- new failure -> exit 1
newrepo
run --write-baseline --check a="exit 0"; ok $RC 0 "write-baseline exits 0 when clean"
test -f "$(baseline_file)"; ok $? 0 "baseline stored in git dir"
run --check a="exit 1"; ok $RC 1 "check that passed in baseline now fails -> exit 1"
has "NEW" "NEW section printed"

# --- baseline-only failure -> exit 0 with warning
newrepo
run --write-baseline --check a="exit 1"; ok $RC 0 "write-baseline exits 0 when a check fails"
run --check a="exit 1"; ok $RC 0 "pre-existing failure -> exit 0"
has "PRE-EXISTING" "PRE-EXISTING section printed"

# --- fixed -> exit 0
newrepo
run --write-baseline --check a="exit 1"
run --check a="exit 0"; ok $RC 0 "fixed check -> exit 0"
has "FIXED" "FIXED section printed"

# --- missing baseline -> exit 2
newrepo
run --check a="exit 0"; ok $RC 2 "missing baseline -> exit 2"
has "--write-baseline" "missing baseline message names the fix"

# --- no checks -> exit 2
newrepo
run --write-baseline; ok $RC 2 "no checks -> exit 2"
has "no checks" "no-checks message"

# --- not a git repo -> exit 2
NG="$(mktemp -d "$TMP/nogit.XXXXXX")"; cd "$NG" || exit 1
run --write-baseline --check a="exit 0"; ok $RC 2 "outside a git repo -> exit 2"

# --- test identifiers: same check, different failing tests -> new
newrepo
printf '#!/bin/sh\necho "FAILED tests/x.py::t1 - boom"\nexit 1\n' > f1.sh
printf '#!/bin/sh\necho "FAILED tests/x.py::t1 - boom"\necho "FAILED tests/x.py::t2 - bang"\nexit 1\n' > f2.sh
printf '#!/bin/sh\necho "FAILED tests/x.py::t9 - zzz"\nexit 1\n' > f3.sh
run --write-baseline --check t="sh f1.sh"
run --check t="sh f2.sh" --json; ok $RC 1 "extra failing test counts as new"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d["new"]==["t: tests/x.py::t2"] else 1)' "$OUT"
ok $? 0 "json new lists only the added test id"
run --check t="sh f1.sh"; ok $RC 0 "same failing test again -> exit 0"
run --check t="sh f3.sh"; ok $RC 1 "different failing test replaces old -> new"
has "t1" "old test listed as fixed"

# --- no identifiers, failing in both -> same
newrepo
run --write-baseline --check a="echo oops; exit 1"
run --check a="echo different oops; exit 3"; ok $RC 0 "no identifiers, fails both times -> pre-existing"

# --- JSON shape
newrepo
run --write-baseline --check a="exit 0"
run --check a="exit 0" --json
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d["new"]==[] and d["status"]=="pass" else 1)' "$OUT"
ok $? 0 "json parses; status pass"

# --- extraction per runner format (read back from the stored baseline)
extract() { # $1 = output text, $2 = expected id
  newrepo
  printf '%s\n' "$1" > out.txt
  run --write-baseline --check t="cat out.txt; exit 1"
  python3 - "$(baseline_file)" "$2" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if sys.argv[2] in d["checks"]["t"]["failures"] else 1)
PY
  ok $? 0 "extracts '$2'"
}
extract ' FAIL  src/a.test.ts > suite > does thing (12ms)' 'src/a.test.ts > suite > does thing'
extract 'FAIL src/b.test.ts (1.2 s)' 'src/b.test.ts'
extract '  ✗ handles empty input [3ms]' 'handles empty input'
extract '  × handles nulls 4ms' 'handles nulls'
extract 'FAILED tests/x.py::test_a - AssertionError: no' 'tests/x.py::test_a'
extract 'not ok 3 widget renders' 'widget renders'
extract 'FAIL: generic thing' 'generic thing'
extract $'\033[31mFAILED tests/y.py::test_b\033[0m' 'tests/y.py::test_b'
extract '2026-10-04T12:00:01Z FAIL: timed thing (0.5s)' 'timed thing'

# --- normalization: durations differ between runs, still the same id
newrepo
run --write-baseline --check t='echo "FAIL: slow one (10ms)"; exit 1'
run --check t='echo "FAIL: slow one (950ms)"; exit 1'; ok $RC 0 "duration noise does not create a new failure"

# --- package.json auto-detect
newrepo
cat > package.json <<'J'
{"scripts":{"build":"exit 0","test":"exit 1","lint":"exit 0","typecheck":"exit 0","test:run":"exit 0"}}
J
run --write-baseline; ok $RC 0 "auto-detect write-baseline"
python3 - "$(baseline_file)" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if list(d["checks"]) == ["lint", "typecheck", "test:run", "build"] else 1)
PY
ok $? 0 "detected lint, typecheck, test:run, build in order"

# --- .ccgm-verify.json fallback
newrepo
echo '{"alpha":"exit 0","beta":"exit 1"}' > .ccgm-verify.json
run --write-baseline; ok $RC 0 ".ccgm-verify.json write-baseline"
run; ok $RC 0 ".ccgm-verify.json gate, beta pre-existing"
has "beta" "beta reported"

# --- --check overrides package.json
newrepo
echo '{"scripts":{"lint":"exit 1"}}' > package.json
run --write-baseline --check only="exit 0"
python3 - "$(baseline_file)" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if list(d["checks"]) == ["only"] else 1)
PY
ok $? 0 "--check wins over package.json"

echo "---"; echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
