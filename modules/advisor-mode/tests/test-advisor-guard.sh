#!/usr/bin/env bash
# Tests for advisor-guard.py — the hard PreToolUse gate that keeps an
# advisor-mode orchestrator from implementing directly. While this session's
# flag file exists, the MAIN agent's file writes are confined to its own
# work-product paths and its Bash is confined to read-only inspection plus
# orchestration verbs; subagent tool calls (hook input carries
# agent_id/agent_type) pass. Per-session state itself (isolation between two
# sessions, auto-on, GC, cleanup) is covered by test-advisor-session.sh.
#
# Exit-code contract under test: 2 = hard block, 0 = allowed.
#
# Run: bash modules/advisor-mode/tests/test-advisor-guard.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GUARD="${MODULE_ROOT}/hooks/advisor-guard.py"
POSTURE="${MODULE_ROOT}/hooks/advisor-posture.py"

PASS=0
FAIL=0

# Every hook input below carries this session id; the flag lives under it.
SID=test-session-a

# A leaked one-off hatch would silently flip every deny-case to allow.
unset ADVISOR_DIRECT

assert_exit() {
    local expected="$1"
    local label="$2"
    local input="$3"
    local actual
    printf '%s' "${input}" | python3 "${GUARD}" >/dev/null 2>&1
    actual=$?
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected exit: ${expected}"
        echo "  actual exit:   ${actual}"
    fi
}

file_json() {
    # $1 tool_name, $2 file_path, $3 optional extra top-level JSON fields
    local extra="${3:-}"
    if [ -n "${extra}" ]; then extra=",${extra}"; fi
    printf '{"tool_name":"%s","tool_input":{"file_path":"%s"},"session_id":"%s"%s}' \
        "$1" "$2" "${SID}" "${extra}"
}

bash_json() {
    # $1 command (must not contain double quotes that break JSON; use jq-free escaping)
    python3 - "$1" "${SID}" <<'PY'
import json, sys
print(json.dumps({"tool_name": "Bash", "tool_input": {"command": sys.argv[1]},
                  "session_id": sys.argv[2]}))
PY
}

TMP=$(mktemp -d -t advisor-guard.XXXXXX)
export HOME="${TMP}/home"
mkdir -p "${HOME}/.claude/advisor-mode" "${HOME}/code/plans" "${HOME}/code/docs" "${HOME}/code/repo/src"
FLAG="${HOME}/.claude/advisor-mode/${SID}"
REPO_FILE="${HOME}/code/repo/src/app.py"

# ─── Mode off: everything passes ─────────────────────────────────────────────

rm -f "${FLAG}"
assert_exit 0 "flag off: Edit in repo allowed" "$(file_json Edit "${REPO_FILE}")"
assert_exit 0 "flag off: git commit allowed" "$(bash_json 'git commit -m "x"')"

# ─── Mode on: subagent and hatch passthrough ─────────────────────────────────

touch "${FLAG}"
assert_exit 2 "flag on: Edit in repo denied" "$(file_json Edit "${REPO_FILE}")"
assert_exit 0 "agent_id present: Edit passes" "$(file_json Edit "${REPO_FILE}" '"agent_id":"abc123"')"
assert_exit 0 "agent_type present: Edit passes" "$(file_json Edit "${REPO_FILE}" '"agent_type":"implementer"')"
assert_exit 2 "empty agent_id does not pass" "$(file_json Edit "${REPO_FILE}" '"agent_id":""')"
ADVISOR_DIRECT=1 assert_exit 0 "env hatch: Edit passes" "$(file_json Edit "${REPO_FILE}")"
assert_exit 0 "inline hatch: bash passes" "$(bash_json 'ADVISOR_DIRECT=1 git commit -m x')"

# ─── File tools: allowed work-product paths ──────────────────────────────────

assert_exit 0 "Write under ~/.claude allowed" "$(file_json Write "${HOME}/.claude/memory/note.md")"
assert_exit 0 "Write under ~/code/plans allowed" "$(file_json Write "${HOME}/code/plans/x/plan.md")"
assert_exit 0 "Write under ~/code/docs allowed" "$(file_json Write "${HOME}/code/docs/research/r.md")"
assert_exit 0 "Write in worktree path allowed" "$(file_json Write "${HOME}/code/repo/.claude/worktrees/agent-x/src/app.py")"
assert_exit 0 "Write in legacy worktree path allowed" "$(file_json Write "${HOME}/code/repo/.worktrees/feat/src/app.py")"
assert_exit 0 "Write plan-mode file allowed" "$(file_json Write "${HOME}/code/repo/.claude/plans/plan.md")"
assert_exit 2 "Write repo source denied" "$(file_json Write "${REPO_FILE}")"
assert_exit 2 "MultiEdit repo source denied" "$(file_json MultiEdit "${REPO_FILE}")"
assert_exit 2 "NotebookEdit repo denied" '{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"'"${HOME}"'/code/repo/nb.ipynb"},"session_id":"'"${SID}"'"}'
assert_exit 2 "mcp write_file repo denied" '{"tool_name":"mcp__filesystem__write_file","tool_input":{"path":"'"${REPO_FILE}"'"},"session_id":"'"${SID}"'"}'
assert_exit 2 "mcp move_file dest repo denied" '{"tool_name":"mcp__filesystem__move_file","tool_input":{"source":"'"${HOME}"'/.claude/a.md","destination":"'"${REPO_FILE}"'"},"session_id":"'"${SID}"'"}'
assert_exit 0 "missing path fails open" '{"tool_name":"Write","tool_input":{},"session_id":"'"${SID}"'"}'
assert_exit 0 "unparseable input fails open" 'not json'

# Scratch space outside HOME (the session scratchpad lives under the temp root).
assert_exit 0 "Write under system tmp allowed" "$(file_json Write "/tmp/advisor-guard-test/scratch.txt")"

# ─── Bash: read-only inspection allowed ──────────────────────────────────────

assert_exit 0 "git status allowed" "$(bash_json 'git status')"
assert_exit 0 "git diff allowed" "$(bash_json 'git diff HEAD~1')"
assert_exit 0 "git log oneline allowed" "$(bash_json 'git log --oneline | head -5')"
assert_exit 0 "git -C path status allowed" "$(bash_json "git -C ${HOME}/code/repo status")"
assert_exit 0 "ls pipe head allowed" "$(bash_json 'ls -la | head -20')"
assert_exit 0 "grep -rn allowed" "$(bash_json 'grep -rn "pattern" src/')"
assert_exit 0 "sed -n print allowed" "$(bash_json 'sed -n 1,10p file.py')"
assert_exit 0 "wc -l allowed" "$(bash_json 'find . -name "*.py" | wc -l')"
assert_exit 0 "cd then status allowed" "$(bash_json 'cd /tmp && git status')"
assert_exit 0 "quoted semicolon not split" "$(bash_json 'grep "foo;bar" file.py')"
assert_exit 0 "stderr dup allowed" "$(bash_json 'git status 2>&1')"
assert_exit 0 "dev null redirect allowed" "$(bash_json 'ls >/dev/null')"

# ─── Bash: orchestration verbs allowed ───────────────────────────────────────

assert_exit 0 "git fetch allowed" "$(bash_json 'git fetch origin')"
assert_exit 0 "git checkout main allowed" "$(bash_json 'git checkout main && git pull --ff-only')"
assert_exit 0 "git worktree remove allowed" "$(bash_json 'git worktree remove .claude/worktrees/agent-x && git worktree prune')"
assert_exit 0 "git branch list allowed" "$(bash_json 'git branch -a')"
assert_exit 0 "gh pr view allowed" "$(bash_json 'gh pr view 42 --json state')"
assert_exit 0 "gh pr merge allowed" "$(bash_json 'gh pr merge 42 --squash')"
assert_exit 0 "gh pr update-branch allowed" "$(bash_json 'gh pr update-branch 42 --rebase')"
assert_exit 0 "gh issue create allowed" "$(bash_json 'gh issue create --title "t" --body "b"')"
assert_exit 0 "gh issue comment allowed" "$(bash_json 'gh issue comment 7 --body "note"')"
assert_exit 0 "gh run view allowed" "$(bash_json 'gh run view 123 --log-failed')"
assert_exit 0 "gh label create allowed" "$(bash_json 'gh label create follow-up --force')"
assert_exit 0 "gh api GET allowed" "$(bash_json 'gh api repos/o/r/pulls/1')"
assert_exit 0 "gh pr checks allowed" "$(bash_json 'gh pr checks 42 --watch')"

# ─── Bash: mutation and execution denied ─────────────────────────────────────

assert_exit 2 "git commit denied" "$(bash_json 'git commit -m "x"')"
assert_exit 2 "git add denied" "$(bash_json 'git add .')"
assert_exit 2 "git push denied" "$(bash_json 'git push origin main')"
assert_exit 2 "git stash denied" "$(bash_json 'git stash')"
assert_exit 2 "git branch -D denied" "$(bash_json 'git branch -D feat')"
assert_exit 2 "git reset denied" "$(bash_json 'git reset --hard HEAD~1')"
assert_exit 2 "sed -i denied" "$(bash_json "sed -i '' 's/a/b/' src/app.py")"
assert_exit 2 "python3 denied" "$(bash_json 'python3 scripts/build.py')"
assert_exit 2 "bash script denied" "$(bash_json 'bash tests/run.sh')"
assert_exit 2 "npm install denied" "$(bash_json 'npm install left-pad')"
assert_exit 2 "npm test denied" "$(bash_json 'npm test')"
assert_exit 2 "gh api POST denied" "$(bash_json 'gh api -X POST repos/o/r/labels -f name=x')"
assert_exit 2 "gh repo delete denied" "$(bash_json 'gh repo delete o/r --yes')"
assert_exit 2 "compound with commit denied" "$(bash_json 'git status && git commit -m x')"
assert_exit 2 "pipe into tee denied" "$(bash_json 'echo x | tee src/app.py')"
assert_exit 2 "command substitution denied" "$(bash_json 'echo $(git commit -m x)')"
assert_exit 0 "backtick with read-only inner allowed" "$(bash_json 'echo `whoami`')"
assert_exit 2 "backtick with mutating inner denied" "$(bash_json 'echo `git commit -m x`')"
assert_exit 2 "xargs denied" "$(bash_json 'find . -name "*.tmp" | xargs rm')"
assert_exit 2 "env wrapper denied" "$(bash_json 'env git commit -m x')"
assert_exit 2 "unknown command denied" "$(bash_json 'terraform apply')"

# Bypass probes (each was a real hole found while building the guard).
assert_exit 2 "newline-hidden commit denied" "$(bash_json 'git status
git commit -m x')"
assert_exit 2 "single-ampersand-hidden commit denied" "$(bash_json 'ls & git commit -m x')"
assert_exit 2 "sed -i with suffix denied" "$(bash_json "sed -i.bak 's/a/b/' src/app.py")"
assert_exit 2 "sed flag-cluster -i denied" "$(bash_json "sed -ni 's/a/b/p' src/app.py")"
assert_exit 2 "git checkout -- pathspec denied" "$(bash_json 'git checkout -- src/app.py')"
assert_exit 0 "git checkout -b branch allowed" "$(bash_json 'git checkout -b 42-fix origin/main')"
assert_exit 0 "fd dup still allowed after ampersand split" "$(bash_json 'git log --oneline 2>&1')"

# Stage-2 review findings (PR #1004): find/sort write-and-exec escapes.
assert_exit 2 "find -exec denied" "$(bash_json 'find . -maxdepth 0 -exec git commit -m x +')"
assert_exit 2 "find -exec shell denied" "$(bash_json "find . -maxdepth 0 -exec bash -c 'echo pwn' +")"
assert_exit 2 "find -delete denied" "$(bash_json "find ${HOME}/code/repo -name '*.py' -delete")"
assert_exit 2 "find -execdir denied" "$(bash_json 'find . -execdir rm {} +')"
assert_exit 2 "sort -o denied" "$(bash_json "sort -o ${HOME}/code/repo/src/app.py /dev/null")"
assert_exit 2 "sort --output denied" "$(bash_json "sort --output=${HOME}/code/repo/src/app.py /dev/null")"
assert_exit 2 "sort attached -oFILE denied" "$(bash_json "sort -o${HOME}/code/repo/src/app.py /dev/null")"
assert_exit 2 "sort clustered -ro denied" "$(bash_json "sort -ro ${HOME}/code/repo/src/app.py /dev/null")"
assert_exit 0 "plain find allowed" "$(bash_json 'find . -name "*.py" -newer ref')"
assert_exit 0 "plain sort in pipe allowed" "$(bash_json 'git diff --stat | sort | head -5')"
assert_exit 0 "git for-each-ref allowed" "$(bash_json 'git for-each-ref --contains HEAD')"
assert_exit 0 "git cat-file allowed" "$(bash_json 'git cat-file -p HEAD')"
assert_exit 0 "git merge-base allowed" "$(bash_json 'git merge-base HEAD origin/main')"
assert_exit 0 "non-string command fails open" '{"tool_name":"Bash","tool_input":{"command":123},"session_id":"'"${SID}"'"}'
assert_exit 0 "non-string file_path fails open" '{"tool_name":"Write","tool_input":{"file_path":42},"session_id":"'"${SID}"'"}'

# ─── Bash: redirection targets scoped to allowed roots ───────────────────────

assert_exit 2 "redirect into repo denied" "$(bash_json "echo hi > ${HOME}/code/repo/out.txt")"
assert_exit 0 "redirect into ~/.claude allowed" "$(bash_json "printf 'on\\n' > ${HOME}/.claude/advisor-mode")"
assert_exit 0 "redirect into tmp allowed" "$(bash_json 'echo hi > /tmp/scratch.txt')"
assert_exit 2 "append into repo denied" "$(bash_json "echo hi >> ${HOME}/code/repo/out.txt")"

# ─── Bash: scratch-scoped file ops ───────────────────────────────────────────

assert_exit 0 "mkdir in tmp allowed" "$(bash_json 'mkdir -p /tmp/advisor-scratch')"
assert_exit 0 "rm in tmp allowed" "$(bash_json 'rm -rf /tmp/advisor-scratch')"
assert_exit 2 "rm in repo denied" "$(bash_json "rm ${HOME}/code/repo/src/app.py")"
assert_exit 2 "mv into repo denied" "$(bash_json "mv /tmp/x.py ${HOME}/code/repo/src/x.py")"
assert_exit 0 "cp within plans allowed" "$(bash_json "cp ${HOME}/code/plans/a.md ${HOME}/code/plans/b.md")"

# ─── Bash: read-only recon (issue #1009) ─────────────────────────────────────

# The two commands an /etp pre-flight was denied on. Every segment is a probe,
# a grouping token, or a read-only git call.
RECON_PROBES='node -v; pnpm -v 2>&1; wrangler --version 2>&1 | head -1; gh auth status 2>&1 | grep -E "Logged in|account" | head -2'
RECON_WHOAMI='wrangler whoami 2>&1 | grep -E "Account|You are" | head -3'
RECON_CD='cd ~/code/repo 2>&1 || { echo "NO SOURCE CLONE"; exit 0; }
echo "origin/main = $(git rev-parse origin/main)"'
assert_exit 0 "recon: tool-probe compound allowed" "$(bash_json "${RECON_PROBES}")"
assert_exit 0 "recon: wrangler whoami pipeline allowed" "$(bash_json "${RECON_WHOAMI}")"
assert_exit 0 "recon: brace-group fallback + rev-parse allowed" "$(bash_json "${RECON_CD}")"

# Tool version/identity probes.
assert_exit 0 "node -v allowed" "$(bash_json 'node -v')"
assert_exit 0 "pnpm -v allowed" "$(bash_json 'pnpm -v')"
assert_exit 0 "wrangler --version allowed" "$(bash_json 'wrangler --version')"
assert_exit 0 "wrangler whoami allowed" "$(bash_json 'wrangler whoami')"
assert_exit 0 "python3 --version allowed" "$(bash_json 'python3 --version')"
assert_exit 0 "xcodebuild -version allowed" "$(bash_json 'xcodebuild -version')"
assert_exit 2 "node script denied" "$(bash_json 'node build.js')"
assert_exit 2 "pnpm install denied" "$(bash_json 'pnpm install')"
assert_exit 2 "wrangler deploy denied" "$(bash_json 'wrangler deploy')"
assert_exit 2 "python3 -c denied" "$(bash_json 'python3 -c "print(1)"')"
assert_exit 2 "docker run denied" "$(bash_json 'docker run x')"
assert_exit 2 "bare node denied" "$(bash_json 'node')"

# Grouping tokens are structure, not commands.
assert_exit 0 "brace group with exit allowed" "$(bash_json '{ echo hi; exit 0; }')"
assert_exit 2 "brace group with commit denied" "$(bash_json '{ git commit -m x; }')"
assert_exit 0 "subshell git status allowed" "$(bash_json '(git status)')"
assert_exit 2 "subshell git push denied" "$(bash_json '(git push)')"
assert_exit 0 "lone closing brace allowed" "$(bash_json '}')"
assert_exit 0 "no-op colon allowed" "$(bash_json ':')"

# Substitution: allowed when every inner command is itself allowlisted.
assert_exit 0 "substitution with read-only inner allowed" "$(bash_json 'echo "x = $(git rev-parse HEAD)"')"
assert_exit 0 "nested substitution allowed" "$(bash_json 'echo $(dirname $(realpath x))')"
assert_exit 0 "backtick date allowed" "$(bash_json 'echo `date`')"
assert_exit 0 "single-quoted substitution is literal" "$(bash_json "echo '\$(git commit -m x)'")"
assert_exit 2 "substitution as the command word denied" "$(bash_json 'echo x && $(dirname $(realpath x))')"
assert_exit 2 "double-quoted mutating substitution denied" "$(bash_json 'echo "$(git commit -m x)"')"
assert_exit 2 "outer redirect after substitution denied" "$(bash_json "\$(cat f) > ${HOME}/code/repo/out.txt")"
assert_exit 2 "redirect inside substitution denied" "$(bash_json "echo \$(echo x > ${HOME}/code/repo/f)")"
assert_exit 2 "process substitution denied" "$(bash_json 'diff <(git status) f')"
assert_exit 2 "unbalanced substitution denied" "$(bash_json 'echo $(git status')"
assert_exit 2 "unpaired backtick denied" "$(bash_json 'gh issue create --body "a `b"')"
assert_exit 2 "substitution nested past the cap denied" "$(bash_json 'echo $(echo $(echo $(echo $(echo $(date)))))')"

# Review round 1 — holes the reviewer reproduced with real side effects.

# P0-1: the shell strips one backslash level from a backtick body, so `\`` in
# there opens a real nested substitution the guard must follow.
assert_exit 2 "nested escaped backticks denied" "$(bash_json 'echo `echo \`git commit -m x\``')"
assert_exit 2 "nested escaped backticks touch denied" "$(bash_json 'echo `echo \`touch ~/code/repo/pwn\``')"
assert_exit 2 "nested escaped backticks sed -i denied" "$(bash_json 'echo `echo \`sed -i s/a/b/ ~/code/repo/f\``')"
assert_exit 2 "three-deep escaped backticks denied" "$(bash_json 'echo `echo \`echo \\\`git commit -m x\\\`\``')"
# $( ) does not strip backslashes, so the inner command never runs there.
assert_exit 0 "escaped backtick inside \$( ) allowed" "$(bash_json 'echo $(echo \`git commit -m x\`)')"

# P0-2: the shell word-splits a substitution's output into real argv, so a
# collapsed span must not stand in for an argument any check reads literally.
assert_exit 2 "substitution as sed flag denied" "$(bash_json 'sed $(echo -i) s/a/b/ ~/code/repo/f')"
assert_exit 2 "substitution as sed long flag denied" "$(bash_json 'sed $(echo --in-place) s/a/b/ ~/code/repo/f')"
assert_exit 2 "backtick as sed flag denied" "$(bash_json 'sed `echo -i` s/a/b/ ~/code/repo/f')"
assert_exit 2 "substitution as find predicate denied" "$(bash_json 'find . $(echo -delete)')"
assert_exit 2 "substitution as find -exec denied" "$(bash_json 'find . $(echo -exec) rm {} +')"
assert_exit 2 "substitution as sort -o denied" "$(bash_json 'sort $(echo -o) ~/code/repo/f ~/code/repo/g')"
assert_exit 2 "substitution as gh api flag denied" "$(bash_json 'gh api repos/o/r/issues/1 $(echo -X) DELETE')"
assert_exit 2 "substitution as scratch-op path denied" "$(bash_json 'rm $(echo ~/code/repo/f)')"
assert_exit 2 "substitution as redirect target denied" "$(bash_json 'echo hi > $(echo ~/code/repo/pwn)')"
assert_exit 2 "substitution as git subcommand denied" "$(bash_json 'git $(echo push)')"
# The guard against over-correcting back into #1009: read-only consumers keep
# taking a checked substitution as an argument.
assert_exit 0 "substitution as echo argument allowed" "$(bash_json 'echo $(git rev-parse HEAD)')"

# P0-3 (issue #1012): a backslash escapes inside double quotes too, so an
# escaped quote can no longer close the span early and hide what follows.
assert_exit 2 "escaped quote then commit denied" "$(bash_json 'echo "\"" ; git commit -m x')"
assert_exit 2 "escaped quote mid-word then commit denied" "$(bash_json 'echo "a\"b" ; git commit -m x')"
assert_exit 2 "escaped quote then repo write denied" "$(bash_json 'echo "\"" ; touch ~/code/repo/pwn')"
assert_exit 2 "escaped backslash then commit denied" "$(bash_json 'echo "\\" ; git commit -m x')"
assert_exit 0 "escaped backslash then status allowed" "$(bash_json 'echo "\\"; git status')"
assert_exit 2 "apostrophe in double quotes still splits" "$(bash_json "echo \"it's\" ; git commit -m x")"
assert_exit 0 "backslash in single quotes is literal" "$(bash_json "echo 'a\\' ; git status")"

# P2-2: arithmetic expansion is denied, with a message about arithmetic
# rather than one claiming the arithmetic body is an unknown command.
arith_err=$(printf '%s' "$(bash_json 'echo $((1+1))')" | python3 "${GUARD}" 2>&1 >/dev/null)
arith_rc=$?
if [ "${arith_rc}" = "2" ] && printf '%s' "${arith_err}" | grep -qi "arithmetic"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: arithmetic expansion denied with its own message"
    echo "  exit: ${arith_rc}"
    echo "  got:  ${arith_err}"
fi

# Nit: a nested denial names its depth once instead of repeating the phrase.
nest_err=$(printf '%s' "$(bash_json 'echo $(echo $(git commit -m x))')" | python3 "${GUARD}" 2>&1 >/dev/null)
if [ "$(printf '%s' "${nest_err}" | grep -c 'inside a substitution')" = "1" ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: nested denial reason names its depth once"
    echo "  got: ${nest_err}"
fi

# Review round 2 — pins for rules the suite could not catch regressing.

# R1-c: the round-1 redirect case passed cwd-dependently — with the path rule
# reverted, the placeholder happened to resolve outside a write root from the
# cwd CI runs in. Assert it from a cwd that IS inside an allowed write root,
# where a reverted rule resolves the placeholder to an allowed path.
mkdir -p "${HOME}/.claude/scratch"
R2_PWD="$(pwd)"
if cd "${HOME}/.claude/scratch"; then
    assert_exit 2 "substitution redirect target denied from an allowed cwd" "$(bash_json 'echo hi > $(echo ~/code/repo/pwn)')"
    assert_exit 2 "substitution scratch path denied from an allowed cwd" "$(bash_json 'rm $(echo ~/code/repo/f)')"
    cd "${R2_PWD}" || exit 1
else
    FAIL=$((FAIL + 1))
    echo "FAIL: could not cd into the allowed-write-root scratch dir"
fi

# R1-d: no per-command exemption is safe. Exempting `git` from the
# placeholder rule reopens both of these, so they pin the rule for `git`
# specifically — `git $(echo push)` does not, since git_segment_allowed
# denies that one on its own.
assert_exit 2 "substitution as git branch flag denied" "$(bash_json 'git branch $(echo -D) x')"
assert_exit 2 "substitution as git checkout pathspec denied" "$(bash_json 'git checkout $(echo --) f')"

# R1-e: the denial for this class names the substitution and the remedy, and
# never quotes the internal placeholder the user did not type.
subst_err=$(printf '%s' "$(bash_json 'sed $(echo -i) s/a/b/ f')" | python3 "${GUARD}" 2>&1 >/dev/null)
subst_rc=$?
if [ "${subst_rc}" = "2" ] \
    && printf '%s' "${subst_err}" | grep -q "inline the value" \
    && ! printf '%s' "${subst_err}" | grep -q "__SUBST__"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: substitution-as-argument denial explains inlining without the placeholder"
    echo "  exit: ${subst_rc}"
    echo "  got:  ${subst_err}"
fi

redir_err=$(printf '%s' "$(bash_json 'echo hi > $(echo ~/code/repo/pwn)')" | python3 "${GUARD}" 2>&1 >/dev/null)
redir_rc=$?
if [ "${redir_rc}" = "2" ] \
    && printf '%s' "${redir_err}" | grep -q "redirect target" \
    && ! printf '%s' "${redir_err}" | grep -q "__SUBST__"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: substitution-as-redirect-target denial names the target class"
    echo "  exit: ${redir_rc}"
    echo "  got:  ${redir_err}"
fi

# Issue #1015: `$'…'` (ANSI-C quoting) is a span where a backslash escapes,
# so `\'` does not close it. Read as a POSIX single-quoted span it closed one
# character early, a phantom span swallowed the separator, and the command
# after it ran unchecked.
assert_exit 2 "ansi-c quoting then commit denied" "$(bash_json "echo \$'a\\'' ; git commit -m x")"
assert_exit 2 "ansi-c quoting then repo write denied" "$(bash_json "echo \$'a\\'' ; touch ~/code/repo/pwn")"
assert_exit 0 "ansi-c escape argument allowed" "$(bash_json "echo \$'\\t' x")"
assert_exit 0 "ansi-c escaped apostrophe then status allowed" "$(bash_json "echo \$'it\\'s fine' ; git status")"
# Inside double quotes `$'` is not an ANSI-C opener — the `;` still splits.
assert_exit 2 "dollar-quote inside double quotes still splits" "$(bash_json "grep \"\$'literal\" f ; git commit -m x")"
assert_exit 0 "unterminated ansi-c quote handled" "$(bash_json "echo \$'unterminated")"

# Issue #1014: the assignment is dropped as an env prefix and the later `$A`
# is a token the guard cannot resolve, so every argument-level check reads
# past it. An argument that begins with an unresolvable expansion is denied
# for any command that is not read-only. $TMPDIR is pinned here because one
# case below turns on it resolving to an allowed write root.
export TMPDIR="${TMP}/tmpdir"
mkdir -p "${TMPDIR}"

assert_exit 2 "assignment then sed \$A denied" "$(bash_json 'A=-i
sed $A s/a/b/ ~/code/repo/f')"
assert_exit 2 "substituted assignment then sed \$A denied" "$(bash_json 'A=$(echo -i)
sed $A s/a/b/ ~/code/repo/f')"
assert_exit 2 "find with \$A predicate denied" "$(bash_json 'find . $A')"
assert_exit 2 "git checkout \$A denied" "$(bash_json 'git checkout $A')"
assert_exit 2 "sort with \$A flag denied" "$(bash_json 'sort $A f g')"
assert_exit 2 "redirect into \$A denied" "$(bash_json 'echo hi > $A')"
assert_exit 2 "rm \$A denied" "$(bash_json 'rm $A')"
assert_exit 2 "node \$A denied" "$(bash_json 'node $A')"
# The edge: the expansion is not the first argument, and still cannot be read.
assert_exit 2 "sed with a trailing \$A denied" "$(bash_json "sed 's/a/b/' \$A")"
# `$_` is the shell's last argument, not this process's environment — so an
# environment lookup for it resolves to the wrong value. `: -i` then
# `sed $_ …` rewrites a file in place exactly like `A=-i`.
assert_exit 2 "shell-only \$_ as sed flag denied" "$(bash_json ': -i
sed $_ s/a/b/ ~/code/repo/f')"
assert_exit 2 "shell-only \$_ as redirect target denied" "$(bash_json 'echo hi > $_')"
# Read-only first words keep taking one — none of them can write it.
assert_exit 0 "echo of an unset var allowed" "$(bash_json 'echo $UNSET_ANYTHING')"
assert_exit 0 "grep with a \$PAT allowed" "$(bash_json 'grep $PAT f')"
assert_exit 0 "rm under a resolved \$TMPDIR allowed" "$(bash_json 'rm -rf $TMPDIR/advisor-scratch')"
assert_exit 0 "single-quoted \$A is literal" "$(bash_json "echo 'literal \$A' ; git status")"

var_err=$(printf '%s' "$(bash_json 'A=-i
sed $A s/a/b/ f')" | python3 "${GUARD}" 2>&1 >/dev/null)
var_rc=$?
if [ "${var_rc}" = "2" ] \
    && printf '%s' "${var_err}" | grep -q 'value written out' \
    && printf '%s' "${var_err}" | grep -q 'VAR'; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: variable-as-argument denial names the expansion and the remedy"
    echo "  exit: ${var_rc}"
    echo "  got:  ${var_err}"
fi

var_redir_err=$(printf '%s' "$(bash_json 'echo hi > $A')" | python3 "${GUARD}" 2>&1 >/dev/null)
var_redir_rc=$?
if [ "${var_redir_rc}" = "2" ] \
    && printf '%s' "${var_redir_err}" | grep -q "redirect target"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: variable-as-redirect-target denial names the target class"
    echo "  exit: ${var_redir_rc}"
    echo "  got:  ${var_redir_err}"
fi

# ─── Posture hook ────────────────────────────────────────────────────────────

posture_json="{\"session_id\":\"${SID}\"}"
posture_out_off=$(rm -f "${FLAG}"; printf '%s' "${posture_json}" | python3 "${POSTURE}" 2>/dev/null; echo "exit=$?")
if printf '%s' "${posture_out_off}" | grep -q "advisor"; then
    FAIL=$((FAIL + 1)); echo "FAIL: posture silent when flag off"
else
    PASS=$((PASS + 1))
fi

touch "${FLAG}"
posture_out_on=$(printf '%s' "${posture_json}" | python3 "${POSTURE}" 2>/dev/null)
if printf '%s' "${posture_out_on}" | grep -q "hookSpecificOutput" && printf '%s' "${posture_out_on}" | grep -qi "advisor mode"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1)); echo "FAIL: posture injects context when flag on"
    echo "  got: ${posture_out_on}"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

python3 -c "import shutil; shutil.rmtree('${TMP}', ignore_errors=True)"
echo ""
echo "advisor-guard tests: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" = "0" ] || exit 1
