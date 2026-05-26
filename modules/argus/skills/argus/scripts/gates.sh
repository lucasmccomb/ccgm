#!/usr/bin/env bash
# gates.sh --spec SPEC --target ID [--state S] [--appearance A] [--probe probe.json]
#          [--tokens tokens.json] [--pairs contrast-pairs.json] [--adapter PATH] [--out gate-result.json]
#
# The deterministic gate runner — the ungameable floor. The judge is NEVER dispatched while
# all_green is false. This script owns the two PLATFORM-AGNOSTIC gates (token_contrast via
# check_contrast.py, a11y_ids via a11y_assert.py) and delegates the platform-specific gates
# (build / lint / type_check / token_compliance / snapshot / flows) to an optional project
# adapter script, which prints a JSON gate-status map on stdout. all_green is computed
# deterministically by verdict_validate.py, never by the model.
#
# Adapter contract: the adapter is invoked as
#   ADAPTER --spec SPEC --target ID --state S --appearance A [--probe probe.json]
# and must print e.g. {"build":"pass","lint":"pass","type_check":"pass","token_compliance":"pass","snapshot":"pass","flows":"pass"}
# See references/adapter-contract.md.
#
# Exit: 0 iff all_green, 1 if a gate failed, 2 on bad input.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REF_DIR="$(cd "$SCRIPT_DIR/../references" && pwd)"

SPEC="" TARGET="" STATE="" APPEARANCE="" PROBE="" TOKENS="" PAIRS="" ADAPTER="" OUT="gate-result.json"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec) SPEC="$2"; shift 2;;
    --target) TARGET="$2"; shift 2;;
    --state) STATE="$2"; shift 2;;
    --appearance) APPEARANCE="$2"; shift 2;;
    --probe) PROBE="$2"; shift 2;;
    --tokens) TOKENS="$2"; shift 2;;
    --pairs) PAIRS="$2"; shift 2;;
    --adapter) ADAPTER="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    *) echo "gates.sh: unknown arg '$1'" >&2; exit 2;;
  esac
done

command -v jq >/dev/null 2>&1 || { echo "gates.sh: jq is required" >&2; exit 2; }
[[ -n "$SPEC" && -f "$SPEC" ]] || { echo "gates.sh: --spec SPEC (existing file) required" >&2; exit 2; }
[[ -n "$TARGET" ]] || { echo "gates.sh: --target ID required" >&2; exit 2; }

SPEC_DIR="$(cd "$(dirname "$SPEC")" && pwd)"
FEATURE="$(jq -r '.feature // ""' "$SPEC")"

# Resolve a repo-relative path: try as-given (cwd), then relative to the spec's dir.
resolve() {
  local p="$1"
  [[ -z "$p" ]] && return 1
  [[ -f "$p" ]] && { echo "$p"; return 0; }
  [[ -f "$SPEC_DIR/$p" ]] && { echo "$SPEC_DIR/$p"; return 0; }
  return 1
}

# --- token_contrast (platform-agnostic) ---
TOKEN_CONTRAST="skip"
[[ -z "$TOKENS" ]] && TOKENS="$(resolve "$(jq -r '.design_system.tokens // ""' "$SPEC")" || true)"
[[ -z "$PAIRS" ]] && PAIRS="$(resolve "$(jq -r '.design_system.contrast_pairs // ""' "$SPEC")" || true)"
if [[ -n "$TOKENS" && -f "$TOKENS" && -n "$PAIRS" && -f "$PAIRS" ]]; then
  if python3 "$SCRIPT_DIR/check_contrast.py" --tokens "$TOKENS" --pairs "$PAIRS" >/dev/null 2>&1; then
    TOKEN_CONTRAST="pass"
  else
    TOKEN_CONTRAST="fail"
  fi
fi

# --- a11y_ids (platform-agnostic) ---
A11Y='{"expected":0,"present":0,"missing":[]}'
if [[ -n "$PROBE" && -f "$PROBE" ]]; then
  A11Y="$(python3 "$SCRIPT_DIR/a11y_assert.py" --probe "$PROBE" --spec "$SPEC" --target "$TARGET" --json || true)"
  echo "$A11Y" | jq empty >/dev/null 2>&1 || A11Y='{"expected":0,"present":0,"missing":[]}'
fi

# --- adapter-provided platform gates ---
ADAPTER_JSON='{}'
if [[ -n "$ADAPTER" ]]; then
  [[ -x "$ADAPTER" || -f "$ADAPTER" ]] || { echo "gates.sh: adapter not found: $ADAPTER" >&2; exit 2; }
  ADAPTER_JSON="$("$ADAPTER" --spec "$SPEC" --target "$TARGET" --state "$STATE" --appearance "$APPEARANCE" ${PROBE:+--probe "$PROBE"})" \
    || { echo "gates.sh: adapter exited non-zero" >&2; exit 2; }
  echo "$ADAPTER_JSON" | jq empty >/dev/null 2>&1 || { echo "gates.sh: adapter output is not JSON" >&2; exit 2; }
fi

BASE='{"build":"skip","lint":"skip","type_check":"skip","token_contrast":"skip","token_compliance":"skip","snapshot":"skip","flows":"skip"}'
GATES="$(jq -n \
  --argjson base "$BASE" --argjson adapter "$ADAPTER_JSON" \
  --arg tc "$TOKEN_CONTRAST" --argjson a11y "$A11Y" \
  '$base * $adapter * {token_contrast: $tc, a11y_ids: $a11y}')"

RESULT="$(jq -n \
  --arg f "$FEATURE" --arg t "$TARGET" --arg s "$STATE" --arg a "$APPEARANCE" --argjson g "$GATES" \
  '{feature:$f, target:$t}
   + (if $s == "" then {} else {state:$s} end)
   + (if $a == "" then {} else {appearance:$a} end)
   + {gates:$g}')"

# Normalize + compute all_green deterministically; verdict_validate exits 2 if malformed.
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
printf '%s\n' "$RESULT" > "$TMP"
if ! python3 "$SCRIPT_DIR/verdict_validate.py" --kind gate "$TMP" > "$OUT" 2>/dev/null; then
  rc=$?
  if [[ $rc -eq 2 ]]; then echo "gates.sh: assembled gate-result is malformed" >&2; exit 2; fi
fi

ALL_GREEN="$(jq -r '.all_green' "$OUT")"
echo "gates.sh: wrote $OUT (all_green=$ALL_GREEN)"
[[ "$ALL_GREEN" == "true" ]]
