#!/usr/bin/env bash
# Differential fuzz for advisor-guard.py: the guard's answer is compared with
# what REAL bash does, not with what the guard was expected to say.
#
# The invariant under test is one line: IF BASH MUTATED THE SANDBOX, THE GUARD
# EXITED 2. Nothing else is asserted — the guard is allowed to over-deny, which
# is this gate's stated direction, but it may never let a write through.
#
# This is the method that found issue #1017 (quoted, ANSI-C and expansion flag
# carriers walking past the literal flag scans). It runs a generated
# carrier x command matrix, so adding a carrier or a command is one line and
# every combination of the two is covered without hand-listing rows.
#
# Everything happens inside a throwaway sandbox: a fake HOME, a fake repo with
# a victim file and a scratch git branch, and the session flag for a fixed
# session id. The real ~/.claude is never read or written, and no command
# reaches the network.
#
# Run: bash modules/advisor-mode/tests/test-advisor-guard-differential.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GUARD="${MODULE_ROOT}/hooks/advisor-guard.py"

PASS=0
FAIL=0
ROWS=0
MUTATIONS=0

SID=diff-session-a
unset ADVISOR_DIRECT

TMP=$(mktemp -d -t advisor-diff.XXXXXX)
export HOME="${TMP}/home"
export TMPDIR="${TMP}/tmpdir"
mkdir -p "${HOME}/.claude/advisor-mode" "${HOME}/code" "${TMPDIR}"
touch "${HOME}/.claude/advisor-mode/${SID}"

REPO="${HOME}/code/repo"
PRISTINE="${TMP}/pristine"
VICTIM="${REPO}/victim.txt"
PWNED="${REPO}/pwn.txt"

cleanup() { python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "${TMP}"; }
trap cleanup EXIT

# ─── Sandbox fixture ─────────────────────────────────────────────────────────

mkdir -p "${PRISTINE}"
(
    cd "${PRISTINE}" || exit 1
    printf 'aaa\n' > victim.txt
    printf 'committed\n' > tracked.txt
    git init -q .
    git config user.email advisor@test.invalid
    git config user.name advisor-test
    git add -A
    git commit -qm base
    git branch scratch-branch
    printf 'dirty\n' > tracked.txt   # `git checkout -- tracked.txt` restores it
) >/dev/null 2>&1

reset_sandbox() {
    python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "${REPO}"
    cp -R "${PRISTINE}" "${REPO}"
}

# Sandbox state: the content of every non-.git file, plus the branch list, so a
# `git branch -D` and a `git checkout --` both register as mutations.
state_hash() {
    python3 - "${REPO}" <<'PY'
import hashlib, os, subprocess, sys
root = sys.argv[1]
h = hashlib.sha256()
for dirpath, dirnames, filenames in os.walk(root):
    if ".git" in dirnames:
        dirnames.remove(".git")
    dirnames.sort()
    for name in sorted(filenames):
        path = os.path.join(dirpath, name)
        h.update(os.path.relpath(path, root).encode())
        try:
            with open(path, "rb") as handle:
                h.update(handle.read())
        except OSError:
            h.update(b"<unreadable>")
branches = subprocess.run(
    ["git", "-C", root, "branch", "--format=%(refname:short)"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
h.update(branches.stdout or b"")
print(h.hexdigest())
PY
}

# BSD sed needs the backup suffix as its own argument; GNU sed does not.
if sed --version >/dev/null 2>&1; then
    SED_TAIL="-e s/aaa/bbb/"
else
    SED_TAIL="'' -e s/aaa/bbb/"
fi

# ─── Carriers: every way to spell one token ──────────────────────────────────

# Each sets CARRY_TOKEN (how the token is written) and CARRY_PREFIX (any
# assignment segments the spelling needs first). A carrier that hides the
# token from a literal scan is exactly the class issue #1017 covers.
CARRIERS="bare squote dquote split backslash ansi ansihex ansioct ansiuni var dqvar indirect default flagvar"

enc_ansi() {  # per-character \xHH / \NNN / \uHHHH bodies
    local fmt="$1" s="$2" i c out=""
    for (( i = 0; i < ${#s}; i++ )); do
        c="${s:${i}:1}"
        out="${out}$(printf "${fmt}" "'${c}")"
    done
    printf '%s' "${out}"
}

carry() {
    local kind="$1" tok="$2"
    CARRY_PREFIX=""
    case "${kind}" in
        bare)      CARRY_TOKEN="${tok}" ;;
        squote)    CARRY_TOKEN="'${tok}'" ;;
        dquote)    CARRY_TOKEN="\"${tok}\"" ;;
        split)     CARRY_TOKEN="${tok:0:1}''${tok:1}" ;;
        backslash) CARRY_TOKEN="\\${tok}" ;;
        ansi)      CARRY_TOKEN="\$'${tok}'" ;;
        ansihex)   CARRY_TOKEN="\$'$(enc_ansi '\\x%02x' "${tok}")'" ;;
        ansioct)   CARRY_TOKEN="\$'$(enc_ansi '\\%03o' "${tok}")'" ;;
        ansiuni)   CARRY_TOKEN="\$'$(enc_ansi '\\u%04x' "${tok}")'" ;;
        var)       CARRY_PREFIX="A=${tok}"; CARRY_TOKEN='$A' ;;
        dqvar)     CARRY_PREFIX="A=${tok}"; CARRY_TOKEN='"$A"' ;;
        indirect)  CARRY_PREFIX="A=B
B=${tok}"; CARRY_TOKEN='${!A}' ;;
        default)   CARRY_TOKEN="\${UNSET_FOR_TEST:-${tok}}" ;;
        flagvar)
            if [ "${tok:0:1}" = "-" ]; then
                CARRY_PREFIX="A=${tok:1}"; CARRY_TOKEN='-$A'
            else
                CARRY_PREFIX="A=${tok}"; CARRY_TOKEN='$A'
            fi ;;
        *) echo "unknown carrier ${kind}" >&2; exit 1 ;;
    esac
}

# ─── Commands: each mutates the sandbox when its token lands ─────────────────

# `gh_api` is guard-side only: asserting on a network call would make the test
# depend on GitHub, and the flag never has to reach gh to be judged.
COMMANDS="sed_i find_delete find_exec sort_o rm_path touch_path redirect_path git_checkout git_branch gh_api"

cmd_token() {
    case "$1" in
        sed_i)          printf '%s' '-i' ;;
        find_delete)    printf '%s' '-delete' ;;
        find_exec)      printf '%s' '-exec' ;;
        sort_o)         printf '%s' '-o' ;;
        rm_path)        printf '%s' "${VICTIM}" ;;
        touch_path)     printf '%s' "${PWNED}" ;;
        redirect_path)  printf '%s' "${PWNED}" ;;
        git_checkout)   printf '%s' '--' ;;
        git_branch)     printf '%s' '-D' ;;
        gh_api)         printf '%s' '-X' ;;
    esac
}

cmd_render() {  # $1 command key, $2 carried token
    case "$1" in
        sed_i)          printf 'sed %s %s %s' "$2" "${SED_TAIL}" "${VICTIM}" ;;
        find_delete)    printf 'find %s -name victim.txt %s' "${REPO}" "$2" ;;
        find_exec)      printf 'find %s -name victim.txt %s rm {} +' "${REPO}" "$2" ;;
        sort_o)         printf 'sort %s %s /dev/null' "$2" "${VICTIM}" ;;
        rm_path)        printf 'rm -f %s' "$2" ;;
        touch_path)     printf 'touch %s' "$2" ;;
        redirect_path)  printf 'echo hi > %s' "$2" ;;
        git_checkout)   printf 'git checkout %s tracked.txt' "$2" ;;
        git_branch)     printf 'git branch %s scratch-branch' "$2" ;;
        gh_api)         printf 'gh api %s POST /repos/o/r/labels' "$2" ;;
    esac
}

cmd_runs_bash() {  # gh rows are judged on the guard's answer alone
    [ "$1" != "gh_api" ]
}

cmd_cwd() {  # git needs to run inside the fake repo
    case "$1" in
        git_checkout|git_branch) printf '%s' "${REPO}" ;;
        *) printf '%s' "${TMP}" ;;
    esac
}

# ─── The loop ────────────────────────────────────────────────────────────────

guard_exit() {
    python3 - "$1" "${SID}" <<'PY' | python3 "${GUARD}" >/dev/null 2>&1
import json, sys
print(json.dumps({"tool_name": "Bash", "tool_input": {"command": sys.argv[1]},
                  "session_id": sys.argv[2]}))
PY
    return $?
}

# reset_sandbox restores the pristine tree, so the "clean" hash is constant.
reset_sandbox
CLEAN=$(state_hash)

for cmd_key in ${COMMANDS}; do
    token=$(cmd_token "${cmd_key}")
    for carrier in ${CARRIERS}; do
        carry "${carrier}" "${token}"
        full=$(cmd_render "${cmd_key}" "${CARRY_TOKEN}")
        if [ -n "${CARRY_PREFIX}" ]; then
            full="${CARRY_PREFIX}
${full}"
        fi
        ROWS=$((ROWS + 1))

        guard_exit "${full}"
        rc=$?

        mutated=0
        if cmd_runs_bash "${cmd_key}"; then
            (cd "$(cmd_cwd "${cmd_key}")" && bash -c "${full}") \
                >/dev/null 2>&1 </dev/null
            if [ "$(state_hash)" != "${CLEAN}" ]; then
                mutated=1
                MUTATIONS=$((MUTATIONS + 1))
                reset_sandbox
            fi
        fi

        # The differential invariant: bash wrote, so the guard had to deny.
        if [ "${mutated}" = "1" ] && [ "${rc}" != "2" ]; then
            FAIL=$((FAIL + 1))
            echo "FAIL: bash mutated the sandbox but the guard allowed it"
            echo "  carrier: ${carrier}   command: ${cmd_key}"
            echo "  guard exit: ${rc}"
            echo "  command: ${full}"
        else
            PASS=$((PASS + 1))
        fi

        # The bash side proves the invariant only where bash actually wrote.
        # This pins the rest of the matrix — no spelling of a mutating flag is
        # allowed, including the gh rows that never run.
        if [ "${rc}" = "2" ]; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
            echo "FAIL: guard allowed a mutating flag"
            echo "  carrier: ${carrier}   command: ${cmd_key}"
            echo "  command: ${full}"
        fi
    done
done

# A matrix where bash never mutated would satisfy the invariant vacuously.
if [ "${MUTATIONS}" -gt 0 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: no row mutated the sandbox — the differential check was vacuous"
fi

echo ""
echo "matrix: ${ROWS} rows, ${MUTATIONS} of them mutated the sandbox under bash"
echo "advisor-guard differential tests: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" = "0" ] || exit 1
