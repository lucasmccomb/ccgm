#!/usr/bin/env bash
# Tests for the diff the analyzer builds itself (lib/draft_proposals.py,
# #1099 Phase 2.2): where an insert lands under its anchor heading, and that
# every generated diff passes `git apply --check` against the real file.
#
# Cases: a bullet joins the bullet list above it; prose gets a paragraph; an
# empty section; the last section of a file with and without a trailing
# newline; a heading-looking line inside a code fence; a lower-level heading
# (### under ##) ending the section only when it is not deeper.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
ROOT=$(mktemp -d -t autoheal_diff.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

REPO="${ROOT}/repo"
mkdir -p "${REPO}"
git -C "${REPO}" init -q -b main

# case <name> <file body printed by printf> <anchor> <insert>: writes the file,
# builds the diff, applies it, and leaves the result in $NEW and the diff in $DIFF.
run_case() {
    local name="$1" body="$2" anchor="$3" insert="$4"
    local path="rules/${name}.md"
    mkdir -p "${REPO}/rules"
    printf "${body}" > "${REPO}/${path}"
    DIFF="$(python3 - "${MODULE_ROOT}/lib/draft_proposals.py" "${REPO}/${path}" "${path}" "${anchor}" "${insert}" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("dp", sys.argv[1])
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)
old = open(sys.argv[2], encoding="utf-8").read()
new = dp.insert_under_heading(old, sys.argv[4], sys.argv[5].split("\n"))
sys.stdout.write("" if new is None else dp.unified_diff(sys.argv[3], old, new))
PY
)"
    printf '%s\n' "${DIFF}" > "${ROOT}/${name}.diff"
    git -C "${REPO}" apply --check "${ROOT}/${name}.diff" 2>"${ROOT}/${name}.err"
    CHECK_RC=$?
    git -C "${REPO}" apply "${ROOT}/${name}.diff" 2>/dev/null
    NEW="$(cat "${REPO}/${path}")"
}

# 1. A bullet joins the list above it.
run_case bullet '# T\n\n## A\n\n- one\n- two\n\n## B\n\ntext\n' "A" "- three"
assert_eq "${CHECK_RC}" "0" "bullet: diff passes git apply --check"
assert_eq "$(printf '%s\n' "${NEW}" | sed -n '5,8p')" "$(printf -- '- one\n- two\n- three\n')" "bullet: joins the list with no blank line between"
assert_contains "${NEW}" "- three

## B" "bullet: blank line kept before the next heading"

# 2. Prose gets its own paragraph.
run_case prose '# T\n\n## A\n\nSome prose here.\n\n## B\n\ntext\n' "A" "New paragraph."
assert_eq "${CHECK_RC}" "0" "prose: diff passes git apply --check"
assert_contains "${NEW}" "Some prose here.

New paragraph.

## B" "prose: paragraph separated by blank lines"

# 3. A bullet after prose starts a new block.
run_case mixed '# T\n\n## A\n\nSome prose here.\n\n## B\n' "A" "- a bullet"
assert_contains "${NEW}" "Some prose here.

- a bullet

## B" "mixed: bullet after prose is its own block"

# 4. An empty section.
run_case empty '# T\n\n## A\n\n## B\n\ntext\n' "A" "- first"
assert_eq "${CHECK_RC}" "0" "empty section: diff passes git apply --check"
assert_contains "${NEW}" "## A

- first

## B" "empty section: insert sits under the heading"

# 5. Last section, trailing newline and none.
run_case last '# T\n\n## A\n\n- one\n' "A" "- two"
assert_eq "${CHECK_RC}" "0" "last section: diff passes git apply --check"
assert_eq "$(tail -n 1 "${REPO}/rules/last.md")" "- two" "last section: file ends with the insert"
run_case nonl '# T\n\n## A\n\n- one' "A" "- two"
assert_eq "${CHECK_RC}" "0" "no trailing newline: diff passes git apply --check"
assert_contains "${NEW}" "- one
- two" "no trailing newline: insert appended"
assert_contains "$(cat "${ROOT}/nonl.diff")" "No newline at end of file" "no trailing newline: marker present in the diff"

# 6. A heading inside a code fence is not the anchor, and does not end a section.
run_case fence '# T\n\n## A\n\n```\n## B\n```\n\n- one\n\n## B\n\nend\n' "B" "- under real B"
assert_eq "${CHECK_RC}" "0" "fence: diff passes git apply --check"
assert_contains "${NEW}" "end

- under real B" "fence: the real B heading is the anchor (fenced one ignored)"

# 7. Deeper headings stay inside the section; a sibling ends it.
run_case levels '# T\n\n## A\n\ntext\n\n### Sub\n\nsub text\n\n## B\n' "A" "- tail of A"
assert_eq "${CHECK_RC}" "0" "levels: diff passes git apply --check"
assert_contains "${NEW}" "sub text

- tail of A

## B" "levels: insert goes after the nested ### block, before the next ##"

# 8. A missing anchor yields no diff.
run_case missing '# T\n\n## A\n' "Nope" "- x"
assert_eq "$(tr -d '\n' < "${ROOT}/missing.diff")" "" "missing anchor: no diff"

echo ""
echo "test-draft-diff.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
