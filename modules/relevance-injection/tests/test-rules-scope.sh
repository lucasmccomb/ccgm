#!/usr/bin/env bash
# test-rules-scope.sh -- /rules-scope generator (Epic 0.5, issue #952).
#
# Two parts:
#
#   Part 1 (deterministic, hermetic, runs everywhere including hosted CI):
#     - default invocation is a dry run: nothing is written, verified via
#       `git status --porcelain` on a real scratch git repo
#     - --write actually writes .claude/settings.json
#     - a dry run against THIS repo's own real install prints a proposal
#       and writes nothing
#
#   Part 2 (Gate 2, model-in-the-loop -- plan.md section 8.4): a full
#     end-to-end check that excluded rules do NOT load and retained rules
#     DO load, using the InstructionsLoaded log as the oracle (Epic 7),
#     exactly as decisions.md's Epic 0.5/Epic 7 experiments did. This part
#     requires an authenticated `claude` CLI, which hosted CI runners never
#     have (.github/workflows/test.yml installs jq/Node/Playwright/pytest
#     but never `claude`, per plan.md section 8.4) -- so it SKIPS itself
#     (not a failure) whenever `claude` is unavailable, and this suite is
#     still safe to wire as a required, always-green CI step.
#
# Portable: bash 3.2, no GNU-only flags. Never touches the real
# ~/.claude/rules/, ~/.claude/hooks/, ~/.claude/settings.json, or
# ~/.claude/.ccgm-manifest.json -- every scratch manifest/settings file
# lives under a temp directory this script creates and removes.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
LIB_DIR="$MODULE_DIR/lib"
RULES_SCOPE="$LIB_DIR/rules_scope.py"
HOOK_UTILS_LIB="$REPO_ROOT/modules/hooks/lib"
INSTRUCTIONS_LOADED_HOOK="$MODULE_DIR/hooks/instructions-loaded-log.py"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 is required" >&2
  exit 1
fi

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/ccgm-rules-scope.XXXXXX")"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

# --- Fixture: a fake CCGM install (manifest + modules/ tree) pointing at
#     THIS repo's real module.json files, so category="tech-specific"
#     detection is real, not fabricated. -------------------------------
FAKE_CCGM_ROOT="$REPO_ROOT"
FAKE_MANIFEST="$WORKDIR/manifest.json"
cat > "$FAKE_MANIFEST" <<EOF
{
  "version": "1.0.0",
  "ccgmRoot": "$FAKE_CCGM_ROOT",
  "modules": ["tailwind", "shadcn", "supabase", "cloudflare", "mcp-development", "git-workflow"]
}
EOF

echo "=== Part 1: deterministic CLI behavior ==="

# --- Test 1: default invocation is a dry run; git status stays clean ---
SCRATCH1="$WORKDIR/rust-repo"
mkdir -p "$SCRATCH1"
( cd "$SCRATCH1" && git init -q && printf '[package]\nname = "x"\n' > Cargo.toml && git add -A && git -c user.email=t@t -c user.name=t commit -q -m init )
python3 "$RULES_SCOPE" "$SCRATCH1" --manifest "$FAKE_MANIFEST" >"$WORKDIR/dryrun-out.txt" 2>&1
PORCELAIN="$(cd "$SCRATCH1" && git status --porcelain)"
if [ -z "$PORCELAIN" ]; then
  pass "default invocation (no --write) leaves git status clean"
else
  fail "default invocation modified the scratch repo: $PORCELAIN"
fi
if grep -q "Dry run" "$WORKDIR/dryrun-out.txt"; then
  pass "default invocation prints a dry-run notice"
else
  fail "expected a dry-run notice in output: $(cat "$WORKDIR/dryrun-out.txt")"
fi
if grep -q "tailwind" "$WORKDIR/dryrun-out.txt"; then
  pass "dry run proposes tailwind (Rust-only repo, no package.json)"
else
  fail "expected tailwind in the proposal for a Rust-only repo: $(cat "$WORKDIR/dryrun-out.txt")"
fi

# --- Test 2: --write actually writes .claude/settings.json -------------
python3 "$RULES_SCOPE" "$SCRATCH1" --manifest "$FAKE_MANIFEST" --write >"$WORKDIR/write-out.txt" 2>&1
if [ -f "$SCRATCH1/.claude/settings.json" ]; then
  pass "--write creates .claude/settings.json"
else
  fail "--write did not create .claude/settings.json: $(cat "$WORKDIR/write-out.txt")"
fi
EXCLUDE_COUNT=$(python3 -c "
import json
data = json.load(open('$SCRATCH1/.claude/settings.json'))
print(len(data.get('claudeMdExcludes', [])))
")
if [ "$EXCLUDE_COUNT" -ge 6 ]; then
  pass "--write proposed at least 6 excludes (all 5 tech-specific modules, tailwind ships 2 files)"
else
  fail "expected >= 6 excludes, got $EXCLUDE_COUNT"
fi

# --- Test 3: re-running --write is idempotent (byte-identical) ---------
cp "$SCRATCH1/.claude/settings.json" "$WORKDIR/settings-after-first-write.json"
python3 "$RULES_SCOPE" "$SCRATCH1" --manifest "$FAKE_MANIFEST" --write >/dev/null 2>&1
if cmp -s "$SCRATCH1/.claude/settings.json" "$WORKDIR/settings-after-first-write.json"; then
  pass "running --write twice is idempotent (byte-identical file)"
else
  fail "second --write run changed the file"
fi

# --- Test 4: a repo with tailwind.config.ts does not get tailwind excluded ---
SCRATCH2="$WORKDIR/web-repo"
mkdir -p "$SCRATCH2"
echo "export default {}" > "$SCRATCH2/tailwind.config.ts"
python3 "$RULES_SCOPE" "$SCRATCH2" --manifest "$FAKE_MANIFEST" >"$WORKDIR/web-out.txt" 2>&1
if grep -qE "^tailwind " "$WORKDIR/web-out.txt"; then
  fail "tailwind was proposed for exclusion despite tailwind.config.ts: $(cat "$WORKDIR/web-out.txt")"
else
  pass "tailwind.config.ts present => tailwind not proposed for exclusion"
fi
if grep -qE "^shadcn " "$WORKDIR/web-out.txt"; then
  pass "shadcn (undetected in this repo) is still proposed"
else
  fail "expected shadcn still proposed: $(cat "$WORKDIR/web-out.txt")"
fi

# --- Test 5: PINNED_FLOOR module (git-workflow) is never proposed -------
if grep -qE "^git-workflow " "$WORKDIR/dryrun-out.txt" "$WORKDIR/web-out.txt"; then
  fail "git-workflow (PINNED_FLOOR) was proposed for exclusion"
else
  pass "git-workflow (PINNED_FLOOR) is never proposed"
fi

# --- Test 6: dry run against THIS repo's own real install ---------------
# Uses this repo as both the "installed manifest" source and the target
# repo being scoped -- exercises the real code path against real data
# without needing the machine's actual ~/.claude/.ccgm-manifest.json.
REAL_MODULES_JSON=$(python3 -c "
import json, pathlib
mods = sorted(p.parent.name for p in pathlib.Path('$REPO_ROOT/modules').glob('*/module.json'))
print(json.dumps(mods))
")
REAL_MANIFEST="$WORKDIR/real-manifest.json"
python3 -c "
import json
mods = json.loads('''$REAL_MODULES_JSON''')
json.dump({'version': '1.0.0', 'ccgmRoot': '$FAKE_CCGM_ROOT', 'modules': mods}, open('$REAL_MANIFEST', 'w'))
"
REPO_CHECK_DIR="$WORKDIR/this-repo-check"
mkdir -p "$REPO_CHECK_DIR"
printf '[package]\nname = "x"\n' > "$REPO_CHECK_DIR/Cargo.toml"
python3 "$RULES_SCOPE" "$REPO_CHECK_DIR" --manifest "$REAL_MANIFEST" >"$WORKDIR/real-out.txt" 2>&1
if [ ! -e "$REPO_CHECK_DIR/.claude/settings.json" ]; then
  pass "dry run against this repo's real module set writes nothing"
else
  fail "dry run against this repo's real module set wrote a settings file"
fi
echo ""
echo "--- Proposal against this repo's real module set (non-web profile) ---"
cat "$WORKDIR/real-out.txt"
echo "---"

echo ""
echo "=== Part 2: end-to-end via InstructionsLoaded (Gate 2, model-in-the-loop) ==="

if ! command -v claude >/dev/null 2>&1; then
  echo "  SKIP: 'claude' CLI not on PATH -- Gate 2 test, expected on hosted CI runners"
  echo "  SKIP: (plan.md section 8.4: this suite is safe to run in CI because this part"
  echo "  SKIP:  degrades to a no-op skip rather than failing when no authenticated"
  echo "  SKIP:  claude CLI is available)"
else
  # Stage hook_utils.py so the InstructionsLoaded hook's `import hook_utils`
  # resolves, matching the exact staging step .github/workflows/test.yml
  # already uses for the other hook test suites. Idempotent.
  mkdir -p "$HOME/.claude/lib"
  cp "$HOOK_UTILS_LIB"/*.py "$HOME/.claude/lib/" 2>/dev/null || true

  E2E_REPO="$WORKDIR/e2e-repo"
  E2E_LOG_DIR="$WORKDIR/e2e-log"
  mkdir -p "$E2E_REPO/.claude" "$E2E_LOG_DIR"
  printf '[package]\nname = "x"\n' > "$E2E_REPO/Cargo.toml"

  cat > "$E2E_REPO/.claude/settings.json" <<EOF
{
  "hooks": {
    "InstructionsLoaded": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "CCGM_RULE_LOADING_DIR=$E2E_LOG_DIR python3 $INSTRUCTIONS_LOADED_HOOK",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
EOF

  # Apply the real generator against the real installed manifest (this
  # machine's actual ~/.claude/.ccgm-manifest.json), so the excluded paths
  # resolve to whatever this machine's real ~/.claude/rules/ symlinks
  # actually point at -- the exact condition InstructionsLoaded will report.
  REAL_MANIFEST_PATH="$HOME/.claude/.ccgm-manifest.json"
  if [ ! -f "$REAL_MANIFEST_PATH" ]; then
    echo "  SKIP: no real CCGM manifest at $REAL_MANIFEST_PATH -- cannot resolve real installed paths"
  else
    python3 "$RULES_SCOPE" "$E2E_REPO" --write >"$WORKDIR/e2e-propose-out.txt" 2>&1
    EXCLUDED_PATHS_FILE="$WORKDIR/excluded-paths.txt"
    python3 -c "
import json
data = json.load(open('$E2E_REPO/.claude/settings.json'))
with open('$EXCLUDED_PATHS_FILE', 'w') as out:
    for p in data.get('claudeMdExcludes', []):
        out.write(p + chr(10))
"
    EXCLUDED_ARGS=()
    if [ -s "$EXCLUDED_PATHS_FILE" ]; then
      while IFS= read -r line; do
        [ -n "$line" ] && EXCLUDED_ARGS+=("$line")
      done < "$EXCLUDED_PATHS_FILE"
    fi

    if [ "${#EXCLUDED_ARGS[@]}" -eq 0 ]; then
      echo "  SKIP: no tech-specific/niche modules installed on this machine to exclude -- nothing to assert"
    else
      ( cd "$E2E_REPO" && claude -p "Say hello in one word." --model sonnet --output-format json >"$WORKDIR/e2e-session-out.json" 2>"$WORKDIR/e2e-session-err.txt" )
      CLAUDE_RC=$?
      if [ "$CLAUDE_RC" -ne 0 ] || [ ! -s "$WORKDIR/e2e-session-out.json" ]; then
        echo "  SKIP: headless claude -p session did not complete (rc=$CLAUDE_RC) -- likely no authenticated session available"
        echo "  SKIP: stderr: $(cat "$WORKDIR/e2e-session-err.txt" 2>/dev/null | head -5)"
      else
        LOG_FILE=$(ls "$E2E_LOG_DIR"/*.jsonl 2>/dev/null | head -1)
        if [ -z "$LOG_FILE" ]; then
          fail "InstructionsLoaded log was never written -- the hook did not fire"
        else
          RESULT=$(python3 "$SCRIPT_DIR/lib/check_e2e_loaded.py" "$LIB_DIR" "$LOG_FILE" "rules/git-workflow.md" "${EXCLUDED_ARGS[@]}")
          if [ "$RESULT" = "OK" ]; then
            pass "excluded rules did not load; retained rule (git-workflow.md) did load"
          else
            fail "InstructionsLoaded assertions failed:
$RESULT"
          fi
        fi
      fi
    fi
  fi
fi

echo ""
echo "test-rules-scope.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
