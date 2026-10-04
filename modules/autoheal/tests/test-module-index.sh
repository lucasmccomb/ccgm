#!/usr/bin/env bash
# Tests for lib/module-index.py (#1099 Phase 2.2): finding the CCGM source
# repo and listing its rule files with their headings.
#
# Coverage:
#   - source repo resolved from the ~/.claude/rules/*.md symlinks
#   - `ccgm_repo_path` in the config overrides the symlinks
#   - an invalid override fails; it is not silently replaced
#   - a copy install (no symlinks, no override) fails with exit 3 and a reason
#   - the index lists every rules file with its H1 and H2 headings
#   - headings inside fenced code are ignored
#   - the index text stays inside its size budget

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INDEX="${MODULE_ROOT}/lib/module-index.py"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
ROOT=$(mktemp -d -t autoheal_index.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

REPO="${ROOT}/repo"
fx_repo "${REPO}"
REAL_REPO="$(cd "${REPO}" && pwd -P)"

# index_run <home> [config path]: prints the JSON, sets RC.
index_run() {
    OUT="$(HOME="$1" CCGM_AUTOHEAL_CONFIG="${2:-$1/none.json}" python3 "${INDEX}" 2>/dev/null)"
    RC=$?
}

# 1. symlink resolution
HOME1="${ROOT}/h1"
fx_home "${HOME1}" "${REPO}"
index_run "${HOME1}"
assert_eq "${RC}" "0" "symlinks: resolves"
assert_eq "$(printf '%s' "${OUT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['how'], d['repo_root'])")" "rules-symlink ${REAL_REPO}" "symlinks: repo root is where the rule files live"

# A symlink into a nested clone path still walks up to the repo root.
HOME1B="${ROOT}/h1b"
mkdir -p "${HOME1B}/.claude/rules"
ln -s "${REPO}/modules/git-workflow/rules/git-workflow.md" "${HOME1B}/.claude/rules/git-workflow.md"
index_run "${HOME1B}"
assert_eq "${RC}" "0" "symlinks: one link is enough"

# 2. config override wins over symlinks
OTHER="${ROOT}/other"
fx_repo "${OTHER}"
printf '{"ccgm_repo_path": "%s"}\n' "${OTHER}" > "${ROOT}/cfg.json"
index_run "${HOME1}" "${ROOT}/cfg.json"
assert_eq "$(printf '%s' "${OUT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['how'], d['repo_root'])")" "config:ccgm_repo_path $(cd "${OTHER}" && pwd)" "override: config key wins over the symlinks"

# 3. invalid override fails, even with good symlinks
printf '{"ccgm_repo_path": "%s/nope"}\n' "${ROOT}" > "${ROOT}/bad.json"
index_run "${HOME1}" "${ROOT}/bad.json"
assert_eq "${RC}" "3" "override: an invalid ccgm_repo_path fails"
assert_contains "${OUT}" "not a CCGM repo" "override: says why"

# 4. copy install
HOME2="${ROOT}/h2"
mkdir -p "${HOME2}/.claude/rules"
cp "${REPO}/modules/git-workflow/rules/git-workflow.md" "${HOME2}/.claude/rules/git-workflow.md"
index_run "${HOME2}"
assert_eq "${RC}" "3" "copy install: exit 3"
assert_contains "${OUT}" "copy install" "copy install: reason names it"
HOME3="${ROOT}/h3"
mkdir -p "${HOME3}"
index_run "${HOME3}"
assert_eq "${RC}" "3" "no rules dir: exit 3"

# 5. index contents
index_run "${HOME1}"
assert_eq "$(printf '%s' "${OUT}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['files']))")" "5" "index: every rules file is listed"
TEXT="$(printf '%s' "${OUT}" | python3 -c "import json,sys; print(json.load(sys.stdin)['text'])")"
assert_contains "${TEXT}" "modules/git-workflow/rules/git-workflow.md" "index: path"
assert_contains "${TEXT}" "# Git Workflow" "index: H1"
assert_contains "${TEXT}" "Never Stash | Pathspecs Resolve From cwd" "index: H2 list"

# 6. fenced headings are not headings; H3 and below are not listed
cat > "${REPO}/modules/cloudflare/rules/cloudflare.md" <<'EOF'
# Cloudflare

```bash
# not a heading
## nor this
```

## Real Section

### Deep

~~~
## inside tilde fence
~~~
EOF
index_run "${HOME1}"
TEXT="$(printf '%s' "${OUT}" | python3 -c "import json,sys; print(json.load(sys.stdin)['text'])")"
LINE="$(printf '%s\n' "${TEXT}" | grep cloudflare.md)"
assert_contains "${LINE}" "Real Section" "fences: real H2 listed"
assert_not_contains "${LINE}" "nor this" "fences: heading in a code fence is ignored"
assert_not_contains "${LINE}" "inside tilde" "fences: tilde fence too"
assert_not_contains "${LINE}" "Deep" "fences: H3 is not indexed"

# 7. size budget: 200 rule files with 30 H2s each still fit
BIG="${ROOT}/big"
fx_repo "${BIG}"
python3 - "${BIG}" <<'PY'
import os, sys
root = sys.argv[1]
for i in range(200):
    d = f"{root}/modules/mod{i:03d}/rules"
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/mod{i:03d}.md", "w") as fh:
        fh.write(f"# Module {i}\n\n" + "".join(f"## Section number {j} of module {i}\n\ntext\n\n" for j in range(30)))
PY
BIG_LEN="$(python3 "${INDEX}" --repo-root "${BIG}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['text']))")"
assert_eq "$([ "${BIG_LEN}" -le 12000 ] && echo ok || echo "${BIG_LEN}")" "ok" "budget: index text stays within 12000 characters"

echo ""
echo "test-module-index.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
