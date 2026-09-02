#!/usr/bin/env bash
# Differential fuzz for advisor-guard.py: the guard's answer is compared with
# what REAL bash does, not with what the guard was expected to say.
#
# The invariant under test is one line: IF BASH MUTATED THE SANDBOX, THE GUARD
# DENIED. Nothing else is asserted — the guard is allowed to over-deny, which
# is this gate's stated direction, but it may never let a write through.
#
# "Denied" means exit 2 AND a denial written to stderr. Exit 2 alone is not
# enough: python itself exits 2 when it cannot open a file, so a missing or
# moved guard would otherwise read as a denial on every row and the suite
# would report a perfect green while nothing was ever checked. The controls
# below catch the same class before the matrix runs.
#
# The matrix axis is BASH's expansion stages, not the normalizer's feature
# list — a matrix built from the implementation's own model cannot find a
# bypass outside that model. Adding a carrier or a command is one line.
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
# ADVISOR_GUARD lets a caller point this at another build of the guard — used
# to prove the harness fails when the guard cannot run, and to re-run the
# matrix against an older revision.
GUARD="${ADVISOR_GUARD:-${MODULE_ROOT}/hooks/advisor-guard.py}"

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
GUARD_IN="${TMP}/guard-in.json"
GUARD_ERR="${TMP}/guard-err.txt"

cleanup() { python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "${TMP}"; }
trap cleanup EXIT

# ─── Running the guard ───────────────────────────────────────────────────────

GUARD_RC=0
GUARD_DENIED=0

# The hook input is built in bash rather than by a python subprocess: the
# matrix is ~200 rows and interpreter startup dominates the runtime. Only the
# four characters the carriers can produce need escaping; anything else would
# make the JSON invalid, the guard would fail open, and the row would report
# loudly as "guard allowed" rather than passing quietly.
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\t'/\\t}"
    printf '%s' "${s}"
}

run_guard() {
    printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"session_id":"%s"}' \
        "$(json_escape "$1")" "${SID}" > "${GUARD_IN}"
    python3 "${GUARD}" < "${GUARD_IN}" >/dev/null 2>"${GUARD_ERR}"
    GUARD_RC=$?
    if [ "${GUARD_RC}" = "2" ] && [ -s "${GUARD_ERR}" ]; then
        GUARD_DENIED=1
    else
        GUARD_DENIED=0
    fi
}

# ─── Controls: the harness must be able to tell allow from deny ─────────────

if [ ! -f "${GUARD}" ]; then
    echo "FAIL: guard not found at ${GUARD} — nothing was checked"
    exit 1
fi

run_guard 'git commit -m x'
if [ "${GUARD_DENIED}" = "1" ]; then
    PASS=$((PASS + 1))
else
    echo "FAIL: positive control — the guard did not deny \`git commit -m x\`"
    echo "  exit: ${GUARD_RC}   stderr: $(cat "${GUARD_ERR}")"
    exit 1
fi

run_guard 'git status'
if [ "${GUARD_RC}" = "0" ] && [ "${GUARD_DENIED}" = "0" ]; then
    PASS=$((PASS + 1))
else
    echo "FAIL: negative control — the guard did not allow \`git status\`"
    echo "  exit: ${GUARD_RC}   stderr: $(cat "${GUARD_ERR}")"
    exit 1
fi

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
# assignment segments the spelling needs first). The first block is
# character-level — quoting and escapes that hide a flag from a literal scan.
# The second is word-level: bash steps that turn ONE typed word into SEVERAL
# argv words, which is the class a per-word model cannot express.
CARRIERS="bare squote dquote split backslash ansi ansihex ansioct ansiuni var dqvar indirect default flagvar dqdollar brace ifs contin glob resolvedglob tildepwd"

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
        # `$"…"` is locale-translation quoting; with no catalogue bash returns
        # the text unchanged, so it is another way to spell the bare token.
        dqdollar)  CARRY_TOKEN="\$\"${tok}\"" ;;
        # Brace expansion: one typed word, two argv words.
        brace)     CARRY_TOKEN="{${tok},${tok}}" ;;
        # $IFS word splitting, with the expansion MID-word (a leading one is
        # already denied by the positional rule, so it would prove nothing).
        ifs)       CARRY_TOKEN=".\$IFS${tok}" ;;
        # Line continuation: bash deletes the backslash-newline pair.
        contin)    CARRY_TOKEN="${tok:0:1}\\
${tok:1}" ;;
        # Pathname expansion against the run directory, which holds a file
        # named after each flag token (see GLOB_BAIT below).
        glob)      CARRY_TOKEN="${tok:0:$(( ${#tok} - 1 ))}*" ;;
        # The same glob, but arriving inside a variable the guard CAN
        # resolve. Bash expands the parameter and THEN globs the result, so
        # the raw word shows nothing; only the value check catches it.
        resolvedglob)
            export DIFF_GLOB_VALUE="${tok:0:$(( ${#tok} - 1 ))}*"
            CARRY_TOKEN='$DIFF_GLOB_VALUE' ;;
        # `~+` is bash's $PWD. Only a path token can carry it, so a flag
        # token falls back to `bare` — the row still has to be denied.
        tildepwd)
            case "${tok}" in
                /*) CARRY_PREFIX="cd $(dirname "${tok}")"
                    CARRY_TOKEN="~+/$(basename "${tok}")" ;;
                *)  CARRY_TOKEN="${tok}" ;;
            esac ;;
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

# Bait for the glob carrier: a file named after each flag token, in the
# directory the non-git rows run from. `find <repo> -dele*` then reaches find
# as `-delete`. Creating these is itself allowed by the gate — temp roots are
# allowed write roots — which is what makes the glob carrier one command away.
python3 - "${TMP}" <<'PY'
import os, sys
for name in ("-i", "-delete", "-exec", "-o", "--", "-D", "-X"):
    open(os.path.join(sys.argv[1], name), "w").close()
PY

# ─── The loop ────────────────────────────────────────────────────────────────

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

        run_guard "${full}"
        denied="${GUARD_DENIED}"

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
        if [ "${mutated}" = "1" ] && [ "${denied}" != "1" ]; then
            FAIL=$((FAIL + 1))
            echo "FAIL: bash mutated the sandbox but the guard allowed it"
            echo "  carrier: ${carrier}   command: ${cmd_key}"
            echo "  guard exit: ${GUARD_RC}"
            echo "  command: ${full}"
        else
            PASS=$((PASS + 1))
        fi

        # The bash side proves the invariant only where bash actually wrote.
        # This pins the rest of the matrix — no spelling of a mutating flag is
        # allowed, including the gh rows that never run.
        if [ "${denied}" = "1" ]; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
            echo "FAIL: guard allowed a mutating flag"
            echo "  carrier: ${carrier}   command: ${cmd_key}"
            echo "  guard exit: ${GUARD_RC}"
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
