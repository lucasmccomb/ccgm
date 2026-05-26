#!/usr/bin/env bash
# Argus module test suite. Pins the deterministic layer: every gate/loop script is exercised
# with fixtures and asserted, so the loop's behavior is regressable. Dependency-free (python3
# stdlib + jq + bash). Run: bash modules/argus/tests/test-argus.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
S="$MOD_DIR/skills/argus/scripts"
R="$MOD_DIR/skills/argus/references"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0 FAIL=0
pass() { PASS=$((PASS+1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# assert_exit EXPECTED "desc" cmd...
assert_exit() {
  local expected="$1" desc="$2"; shift 2
  "$@" >/dev/null 2>&1; local rc=$?
  if [[ "$rc" -eq "$expected" ]]; then pass "$desc (exit $rc)"; else fail "$desc (got exit $rc, want $expected)"; fi
}
# assert_eq ACTUAL EXPECTED "desc"
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3 (got '$1', want '$2')"; fi
}

make_png() { # make_png PATH GRAY(0-255)
  python3 - "$1" "${2:-0}" <<'PY'
import sys, zlib, struct
p, val = sys.argv[1], int(sys.argv[2])
w = h = 2
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
raw = b''.join(b'\x00' + bytes([val, val, val] * w) for _ in range(h))
png = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(raw))
       + chunk(b'IEND', b''))
open(p, 'wb').write(png)
PY
}

echo "=== Argus module tests ==="

# --- check_contrast.py ---
echo "--- check_contrast ---"
assert_exit 0 "contrast: template palette passes (with whitelist)" \
  python3 "$S/check_contrast.py" --tokens "$R/_template/tokens.json" --pairs "$R/_template/contrast-pairs.json"
cat > "$TMP/bad-tokens.json" <<'JSON'
{ "colors": { "surface": {"light":"#FFFFFF"}, "textPrimary": {"light":"#A0A0A0"} } }
JSON
cat > "$TMP/bad-pairs.json" <<'JSON'
{ "pairs": [ { "fg": "textPrimary", "bg": "surface", "min": 4.5 } ] }
JSON
assert_exit 1 "contrast: low-contrast pair fails" \
  python3 "$S/check_contrast.py" --tokens "$TMP/bad-tokens.json" --pairs "$TMP/bad-pairs.json" --appearances light
# known ratio: black on white == 21:1
cat > "$TMP/bw-tokens.json" <<'JSON'
{ "colors": { "bg": "#FFFFFF", "fg": "#000000" } }
JSON
cat > "$TMP/bw-pairs.json" <<'JSON'
{ "pairs": [ { "fg": "fg", "bg": "bg", "min": 4.5 } ] }
JSON
ratio="$(python3 "$S/check_contrast.py" --tokens "$TMP/bw-tokens.json" --pairs "$TMP/bw-pairs.json" --appearances default --json | jq -r '.pairs[0].ratio')"
assert_eq "$ratio" "21.0" "contrast: black-on-white computes 21.0"

# --- spec_lint.py ---
echo "--- spec_lint ---"
assert_exit 0 "spec_lint: template spec is valid (needed-ref is worklist, not error)" \
  python3 "$S/spec_lint.py" "$R/_template/spec.json"
echo '{ "feature": "x", "adapter": "web" }' > "$TMP/bad-spec.json"
assert_exit 1 "spec_lint: missing design_system + targets fails" \
  python3 "$S/spec_lint.py" "$TMP/bad-spec.json"
# present reference with a missing file must fail
mkdir -p "$TMP/spec"
cat > "$TMP/spec/spec.json" <<'JSON'
{ "feature": "x", "adapter": "web", "design_system": {"tokens":"tokens.json"},
  "targets": [ { "id": "list", "route": "/x", "states": ["populated"],
    "references": [ {"state":"populated","appearance":"light","status":"present","file":"references/missing.png"} ] } ] }
JSON
assert_exit 1 "spec_lint: present reference with missing file fails" \
  python3 "$S/spec_lint.py" "$TMP/spec/spec.json"

# --- a11y_assert.py ---
echo "--- a11y_assert ---"
cat > "$TMP/probe.json" <<'JSON'
{ "role":"screen","accessibilityIdentifier":"screen.habits",
  "children":[ {"id":"button.createHabit"}, {"data-testid":"row.habit.42"}, {"identifier":"row.habit.7"} ] }
JSON
assert_exit 0 "a11y: all contract ids present (incl prefix family)" \
  python3 "$S/a11y_assert.py" --probe "$TMP/probe.json" --contract '["screen.habits","button.createHabit","row.habit.*"]'
assert_exit 1 "a11y: missing id fails" \
  python3 "$S/a11y_assert.py" --probe "$TMP/probe.json" --contract '["screen.habits","button.deleteHabit"]'
missing="$(python3 "$S/a11y_assert.py" --probe "$TMP/probe.json" --contract '["nope.*"]' --json | jq -c '.missing')"
assert_eq "$missing" '["nope.*"]' "a11y: prefix family with no match reported missing"

# --- loop_state.py ---
echo "--- loop_state ---"
ST="$TMP/state.json"
python3 "$S/loop_state.py" init --state "$ST" --feature x --target "list/populated/dark" --reference-source human >/dev/null
echo '{"all_pass":false,"failed_dimensions":["layout_spacing"]}' > "$TMP/v-fail.json"
echo '{"all_pass":true,"failed_dimensions":[]}' > "$TMP/v-pass.json"
out="$(python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-fail.json" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -r '.decision.consecutive_passes')" "0" "loop: fail keeps streak at 0"
assert_eq "$(echo "$out" | jq -rc '.decision.fix_dimensions')" '["layout_spacing"]' "loop: fail surfaces fix dimension"
out="$(python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-pass.json" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -r '.decision.consecutive_passes')" "1" "loop: first pass => streak 1"
assert_eq "$(echo "$out" | jq -r '.decision.should_signoff')" "false" "loop: one pass does not sign off"
out="$(python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-pass.json" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -r '.decision.consecutive_passes')" "2" "loop: second consecutive pass => streak 2"
assert_eq "$(echo "$out" | jq -r '.decision.should_signoff')" "true" "loop: two passes => sign off"
# freeze after 3 attempts on the same dimension
python3 "$S/loop_state.py" init --state "$ST" --feature x --target t >/dev/null
for _ in 1 2; do python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-fail.json" --rubric "$R/rubric.json" >/dev/null; done
out="$(python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-fail.json" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -rc '.decision.frozen')" '["layout_spacing"]' "loop: dimension frozen after 3 attempts"
assert_eq "$(echo "$out" | jq -rc '.decision.fix_dimensions')" '[]' "loop: frozen dim removed from fix list"
# unchanged confirm bumps streak; gate-fail resets it
python3 "$S/loop_state.py" init --state "$ST" --feature x --target t >/dev/null
python3 "$S/loop_state.py" record --state "$ST" --verdict "$TMP/v-pass.json" --rubric "$R/rubric.json" >/dev/null
out="$(python3 "$S/loop_state.py" unchanged --state "$ST" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -r '.decision.should_signoff')" "true" "loop: hash-suppressed confirm counts as 2nd pass"
out="$(python3 "$S/loop_state.py" gate-fail --state "$ST" --rubric "$R/rubric.json")"
assert_eq "$(echo "$out" | jq -r '.decision.consecutive_passes')" "0" "loop: gate-fail resets the streak"

# --- verdict_validate.py ---
echo "--- verdict_validate ---"
cat > "$TMP/verdict-good.json" <<'JSON'
{ "iteration":1,"feature":"x","target":"list",
  "dimensions":{"visual_fidelity":{"score":1,"anchor":"reference","evidence":"e"}},
  "all_pass":true,"failed_dimensions":[] }
JSON
assert_exit 0 "verdict: consistent verdict validates" \
  python3 "$S/verdict_validate.py" --kind verdict "$TMP/verdict-good.json" --rubric "$R/rubric.json"
cat > "$TMP/verdict-liar.json" <<'JSON'
{ "iteration":1,"feature":"x","target":"list",
  "dimensions":{"visual_fidelity":{"score":1,"anchor":"reference","evidence":"e"},
                "layout_spacing":{"score":0.5,"anchor":"design-system","evidence":"e"}},
  "all_pass":true,"failed_dimensions":[] }
JSON
norm="$(python3 "$S/verdict_validate.py" --kind verdict "$TMP/verdict-liar.json" --rubric "$R/rubric.json" 2>/dev/null)"
assert_eq "$(echo "$norm" | jq -r '.all_pass')" "false" "verdict: 0.5 below threshold => all_pass corrected to false"
assert_eq "$(echo "$norm" | jq -rc '.failed_dimensions')" '["layout_spacing"]' "verdict: failed_dimensions re-derived"
assert_exit 1 "verdict: self-report disagreement signals exit 1" \
  python3 "$S/verdict_validate.py" --kind verdict "$TMP/verdict-liar.json" --rubric "$R/rubric.json"
cat > "$TMP/gate-liar.json" <<'JSON'
{ "feature":"x","target":"list","gates":{"build":"fail","a11y_ids":{"expected":1,"present":1,"missing":[]}},"all_green":true }
JSON
norm="$(python3 "$S/verdict_validate.py" --kind gate "$TMP/gate-liar.json" 2>/dev/null)"
assert_eq "$(echo "$norm" | jq -r '.all_green')" "false" "gate: failing gate forces all_green false"

# --- image_unchanged.sh ---
echo "--- image_unchanged ---"
make_png "$TMP/a.png" 0
cp "$TMP/a.png" "$TMP/a2.png"
make_png "$TMP/b.png" 255
assert_eq "$(bash "$S/image_unchanged.sh" "$TMP/a.png" "$TMP/a2.png" | jq -r '.unchanged')" "true" "image: identical renders => unchanged true"
assert_eq "$(bash "$S/image_unchanged.sh" "$TMP/a.png" "$TMP/b.png" | jq -r '.unchanged')" "false" "image: different renders => unchanged false"
assert_eq "$(bash "$S/image_unchanged.sh" "$TMP/none.png" "$TMP/a.png" | jq -r '.unchanged')" "false" "image: no baseline => unchanged false"

# --- gates.sh (integration: module gates compose, all_green derived) ---
echo "--- gates.sh ---"
mkdir -p "$TMP/g"
cp "$R/_template/tokens.json" "$TMP/g/tokens.json"
cp "$R/_template/contrast-pairs.json" "$TMP/g/contrast-pairs.json"
cat > "$TMP/g/probe.json" <<'JSON'
{ "accessibilityIdentifier":"screen.habits","children":[{"id":"button.createHabit"},{"id":"state.habits.empty"}] }
JSON
cat > "$TMP/g/spec.json" <<'JSON'
{ "feature":"habits","adapter":"web","design_system":{"tokens":"tokens.json","contrast_pairs":"contrast-pairs.json"},
  "targets":[ {"id":"list","route":"/h","states":["empty"],
    "a11y_contract":["screen.habits","button.createHabit","state.habits.empty"]} ] }
JSON
assert_exit 0 "gates: green when contrast passes + a11y ids present (no adapter)" \
  bash "$S/gates.sh" --spec "$TMP/g/spec.json" --target list --state empty --appearance light --probe "$TMP/g/probe.json" --out "$TMP/g/gate-result.json"
assert_eq "$(jq -r '.all_green' "$TMP/g/gate-result.json")" "true" "gates: all_green true on the happy path"
assert_eq "$(jq -r '.gates.token_contrast' "$TMP/g/gate-result.json")" "pass" "gates: token_contrast pass recorded"
# missing a required id => red floor
cat > "$TMP/g/probe-bad.json" <<'JSON'
{ "accessibilityIdentifier":"screen.habits","children":[{"id":"button.createHabit"}] }
JSON
assert_exit 1 "gates: red when a required a11y id is missing" \
  bash "$S/gates.sh" --spec "$TMP/g/spec.json" --target list --state empty --probe "$TMP/g/probe-bad.json" --out "$TMP/g/gate-bad.json"
assert_eq "$(jq -r '.all_green' "$TMP/g/gate-bad.json")" "false" "gates: all_green false when floor is red"

echo ""
echo "==================================="
echo "  Argus: $PASS passed, $FAIL failed"
echo "==================================="
[[ "$FAIL" -eq 0 ]]
