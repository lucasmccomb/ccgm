#!/usr/bin/env bash
# Asserts each long-report command ends with the report page step, and that
# all three /audit modes reach it. Exits non-zero on any failure.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fail=0
check() { # file fixed-string description
  if grep -qF -- "$2" "$1"; then echo "PASS $3"; else echo "FAIL $3 ($1 lacks: $2)"; fail=1; fi
}
BIN='${CCGM_BIN:-$HOME/.claude/bin}/ccgm-md-page'
NOTE='ccgm-md-page not installed; the report is at'

for f in modules/research/commands/research.md \
         modules/deepresearch/commands/deepresearch.md \
         modules/brand-naming/commands/brand.md \
         modules/commands-extra/skills/audit/SKILL.md \
         modules/dreaming/commands/dream-scorecard.md; do
  check "$ROOT/$f" "$BIN" "$f: absolute-path form"
  check "$ROOT/$f" "$NOTE" "$f: not-installed note"
  check "$ROOT/$f" "artifact-design" "$f: Artifact branch"
done
check "$ROOT/modules/dreaming/commands/dream-scorecard.md" "dataviz" "dream-scorecard: dataviz chart"

# Audit: each mode's report-writing phase must point at the shared step.
A="$ROOT/modules/commands-extra/skills/audit/SKILL.md"
for h in '### Phase M6:' '### Phase C2:' '### Phase 6:'; do
  if awk -v h="$h" 'index($0,h)==1{on=1;next} on&&/^### Phase /{exit} on&&/Report page step/{found=1} END{exit !found}' "$A"; then
    echo "PASS audit $h reaches the page step"
  else
    echo "FAIL audit $h does not reference the page step"; fail=1
  fi
done
exit $fail
