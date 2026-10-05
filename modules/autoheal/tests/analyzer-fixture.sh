#!/usr/bin/env bash
# Shared fixtures for the analyzer tests. Source this file; it defines
# functions only and runs nothing.
#
#   fx_repo <dir>                   git repo shaped like CCGM: start.sh plus
#                                   modules/{code-quality,common-mistakes,
#                                   git-workflow,cloudflare,branch-guard}/rules
#   fx_home <home> <repo>           HOME whose ~/.claude/rules/*.md symlink
#                                   into the repo (what `start.sh` installs)
#   fx_err <class>                  error text that classifies as <class>
#   fx_events <state> <end-date> <tool> <cmd_head> <class> <error> <rows>
#                                   <sessions> [days]
#                                   tool_failure rows spread over the last
#                                   [days] (default 2) days, plus a counts/ file
#   fx_curl <bin dir> <fake dir>    install the fake curl; export FAKE_CURL_DIR
#   fx_answer <file> <json> [stop_reason] [in] [out] [cache_create] [cache_read]
#                                   stage a Messages API reply whose text is <json>
#   fx_calls <fake dir> <endpoint>  number of recorded calls to an endpoint

FX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fx_repo() {
    local dir="$1"
    mkdir -p "${dir}/modules"
    printf '#!/usr/bin/env bash\n' > "${dir}/start.sh"
    mkdir -p "${dir}/modules/code-quality/rules" "${dir}/modules/common-mistakes/rules" \
             "${dir}/modules/git-workflow/rules" "${dir}/modules/cloudflare/rules" \
             "${dir}/modules/branch-guard/rules"
    cat > "${dir}/modules/code-quality/rules/code-quality.md" <<'EOF'
# Code Quality Standards

## Simplest Implementation

Choose the simplest implementation that fully meets the requirements.

## Code Standards

- When adding env vars, update the corresponding `.env.example`.
- Use functional React components with explicit TypeScript prop interfaces.

## Testing

Write tests for new features.
EOF
    cat > "${dir}/modules/common-mistakes/rules/common-mistakes.md" <<'EOF'
# Common Mistakes to Avoid

## 1. Branching Without Checking Open PRs

Run `gh pr list --state open` first.

## Adding New Mistakes

Add an entry when a pattern cost 30 minutes.
EOF
    cat > "${dir}/modules/git-workflow/rules/git-workflow.md" <<'EOF'
# Git Workflow

## Never Stash

Commit instead.

## Pathspecs Resolve From cwd

`git add packages/foo/...` fails when run from inside another sub-package.
EOF
    cat > "${dir}/modules/cloudflare/rules/cloudflare.md" <<'EOF'
# Cloudflare

## Pages vs Workers

Use wrangler deploy for Workers.
EOF
    cat > "${dir}/modules/branch-guard/rules/branch-guard.md" <<'EOF'
# Branch Guard

## Escape Hatch

ALLOW_MAIN_COMMIT=1 only when asked.
EOF
    # The validation gate runs the repo's own checks against origin/main.
    mkdir -p "${dir}/tests"
    printf '#!/usr/bin/env bash\nexit 0\n' > "${dir}/tests/test-no-personal-data.sh"
    printf '#!/usr/bin/env bash\nexit 0\n' > "${dir}/tests/test-modules.sh"
    git -C "${dir}" init -q -b main
    git -C "${dir}" add -A
    git -C "${dir}" -c core.hooksPath=/dev/null -c user.email=t@example.com -c user.name=t commit -q -m fixture
    git -C "${dir}" update-ref refs/remotes/origin/main HEAD
}

fx_home() {
    local home="$1" repo="$2" f
    mkdir -p "${home}/.claude/rules"
    for f in "${repo}"/modules/*/rules/*.md; do
        ln -s "${f}" "${home}/.claude/rules/$(basename "${f}")"
    done
}

# fx_err <class>: synthetic error text that classifies as <class>. The aggregator
# classifies again from the stored error text, so a fixture row's text has to match.
fx_err() {
    case "$1" in
        zsh_not_found) echo "(eval):1: ==== not found" ;;
        zsh_no_matches) echo "zsh: no matches found: *.x" ;;
        no_such_file) echo "x: No such file or directory" ;;
        permission_denied) echo "x: Permission denied" ;;
        pathspec_no_match) echo "error: pathspec 'x' did not match any file" ;;
        command_not_found) echo "x: command not found" ;;
        *) echo "boom $1" ;;
    esac
}

fx_events() {
    python3 - "$@" <<'PY'
import datetime as dt
import json
import os
import sys

state, end, tool, head, cls, error, rows, sessions = sys.argv[1:9]
days = int(sys.argv[9]) if len(sys.argv) > 9 else 2
rows, sessions = int(rows), int(sessions)
end_d = dt.date.fromisoformat(end)
os.makedirs(os.path.join(state, "events"), exist_ok=True)
os.makedirs(os.path.join(state, "counts"), exist_ok=True)
per_day = {}
for i in range(rows):
    day = (end_d - dt.timedelta(days=i % days)).isoformat()
    per_day.setdefault(day, []).append({
        "kind": "tool_failure",
        "timestamp": f"{day}T10:{i % 60:02d}:00+00:00",
        "session_id": f"s-{i % sessions}",
        "tool_name": tool,
        "redacted_command": f"{head} --flag-{i} ====",
        "cmd_head": head,
        "error": error,
        "error_class": cls,
        "cwd": "/Users/someone/code/demo-repos/demo-0",
    })
for day, recs in per_day.items():
    with open(os.path.join(state, "events", day + ".jsonl"), "a", encoding="utf-8") as fh:
        for rec in recs:
            fh.write(json.dumps(rec) + "\n")
    counts_path = os.path.join(state, "counts", day + ".json")
    counts = {}
    if os.path.isfile(counts_path):
        counts = json.load(open(counts_path, encoding="utf-8"))
    counts[tool] = 500
    json.dump(counts, open(counts_path, "w", encoding="utf-8"))
PY
}

fx_curl() {
    local bindir="$1" fakedir="$2"
    mkdir -p "${bindir}" "${fakedir}"
    cp "${FX_DIR}/fixtures/fake-curl.py" "${bindir}/curl"
    chmod +x "${bindir}/curl"
}

fx_answer() {
    # fx_answer <file> <answer json text> [stop_reason] [in] [out] [cache_create] [cache_read]
    python3 - "$@" <<'PY'
import json
import sys

path, text = sys.argv[1], sys.argv[2]
stop = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else "end_turn"
nin = int(sys.argv[4]) if len(sys.argv) > 4 else 1200
nout = int(sys.argv[5]) if len(sys.argv) > 5 else 240
cc = int(sys.argv[6]) if len(sys.argv) > 6 else 0
cr = int(sys.argv[7]) if len(sys.argv) > 7 else 0
usage = {"input_tokens": nin, "output_tokens": nout}
if cc:
    usage["cache_creation_input_tokens"] = cc
if cr:
    usage["cache_read_input_tokens"] = cr
content = [{"type": "text", "text": text}] if text else []
json.dump({"id": "msg_fx", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
           "stop_reason": stop, "usage": usage, "content": content},
          open(path, "w", encoding="utf-8"))
PY
}

fx_calls() {
    local n
    n=$(grep -cx "$2" "$1/calls.log" 2>/dev/null) || true
    echo "${n:-0}"
}

# Assertions. Callers define PASS=0 and FAIL=0 and print the totals.
assert_eq() {
    if [ "$1" = "$2" ]; then PASS=$((PASS + 1)); else
        FAIL=$((FAIL + 1)); echo "FAIL: $3"; echo "  expected: $2"; echo "  actual:   $1"
    fi
}
assert_contains() {
    case "$1" in *"$2"*) PASS=$((PASS + 1)) ;; *)
        FAIL=$((FAIL + 1)); echo "FAIL: $3"; echo "  expected substring: $2"; echo "  actual (first 600): ${1:0:600}" ;;
    esac
}
assert_not_contains() {
    case "$1" in *"$2"*)
        FAIL=$((FAIL + 1)); echo "FAIL: $3"; echo "  unexpected substring: $2" ;; *) PASS=$((PASS + 1)) ;;
    esac
}
assert_file_exists() {
    if [ -f "$1" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: $2 (missing $1)"; fi
}
assert_no_file() {
    if [ ! -e "$1" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: $2 (found $1)"; fi
}
# json_get <file> <python expression over d>: print one value from a JSON file.
json_get() {
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print($2)" "$1"
}
# jsonl_get <file> <line number, 1-based> <python expression over d>
jsonl_get() {
    python3 -c "
import json,sys
d=json.loads(open(sys.argv[1]).read().splitlines()[int(sys.argv[2])-1])
print($3)" "$1" "$2"
}
