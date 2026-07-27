#!/usr/bin/env bash
# Runs the clone_identity unit suite (stdlib unittest, no pytest needed) and
# smoke-tests the CLI end to end against a throwaway tree.
set -euo pipefail

TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
MODULE_DIR="$(dirname "$TEST_DIR")"
LIB="${MODULE_DIR}/lib/clone_identity.py"

echo "== unit suite =="
python3 "${TEST_DIR}/test_clone_identity.py"

echo
echo "== CLI smoke =="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REGISTRY="${TMP}/port-registry.json"
cat > "$REGISTRY" <<'JSON'
{
  "_block_size": 16,
  "repos": {
    "demo": { "frontend": 5221, "backend": 8835, "clones_per_workspace": 3 }
  }
}
JSON

CLONE="${TMP}/code/demo-workspaces/demo-w1/demo-w1-c0"
mkdir -p "$CLONE"
# Seed the exact drift that motivated this module: another clone's file.
printf 'WORKSPACE_NUMBER=0\nCLONE_NUMBER=1\nAGENT_ID=agent-w0-c1\nPORT_OFFSET=1\nFRONTEND_PORT=5222\nBACKEND_PORT=8836\nKEEP_ME=yes\n' \
  > "${CLONE}/.env.clone"

echo "-- audit (expects drift, exit 1)"
if python3 "$LIB" --registry "$REGISTRY" audit --root "${TMP}/code"; then
  echo "FAIL: audit should exit non-zero on drift" >&2
  exit 1
fi

echo "-- dry-run must not write"
python3 "$LIB" --registry "$REGISTRY" repair "$CLONE" --dry-run >/dev/null
grep -q '^AGENT_ID=agent-w0-c1$' "${CLONE}/.env.clone" || {
  echo "FAIL: --dry-run modified the file" >&2; exit 1; }

echo "-- repair --all"
python3 "$LIB" --registry "$REGISTRY" repair --all --root "${TMP}/code"

for expected in 'AGENT_ID=agent-w1-c0' 'WORKSPACE_NUMBER=1' 'CLONE_NUMBER=0' \
                'PORT_OFFSET=3' 'FRONTEND_PORT=5224' 'BACKEND_PORT=8838' 'KEEP_ME=yes'; do
  grep -q "^${expected}$" "${CLONE}/.env.clone" || {
    echo "FAIL: expected ${expected} in repaired .env.clone" >&2
    cat "${CLONE}/.env.clone" >&2
    exit 1; }
done

echo "-- audit is now clean (exit 0)"
python3 "$LIB" --registry "$REGISTRY" audit --root "${TMP}/code"

echo "-- repair is idempotent"
OUT="$(python3 "$LIB" --registry "$REGISTRY" repair "$CLONE")"
case "$OUT" in *ok:*) ;; *) echo "FAIL: second repair should report ok, got: $OUT" >&2; exit 1;; esac

echo "-- workspace-table matches derivation"
python3 "$LIB" --registry "$REGISTRY" workspace-table "${TMP}/code/demo-workspaces/demo-w1" \
  | grep -q '| c0 | demo-w1-c0/ | agent-w1-c0 | 5224 | 8838 |' || {
  echo "FAIL: workspace-table row mismatch" >&2; exit 1; }

echo
echo "== SessionStart hook =="
HOOK="${MODULE_DIR}/hooks/clone-identity-sync.py"
# The hook resolves the registry through clone_identity's default (~/.claude),
# so point the whole derivation at the fixture via a fake HOME.
FAKE_HOME="${TMP}/home"
mkdir -p "${FAKE_HOME}/.claude/lib"
cp "$LIB" "${FAKE_HOME}/.claude/lib/"
cp "$REGISTRY" "${FAKE_HOME}/.claude/port-registry.json"

HOOK_CLONE="${TMP}/code/demo-workspaces/demo-w2/demo-w2-c1"
mkdir -p "$HOOK_CLONE"
printf 'AGENT_ID=agent-w0-c1\nFRONTEND_PORT=5222\n' > "${HOOK_CLONE}/.env.clone"

echo "-- repairs a drifted clone and announces it"
OUT="$(printf '{"source":"startup","cwd":"%s"}' "$HOOK_CLONE" | HOME="$FAKE_HOME" python3 "$HOOK")"
case "$OUT" in *clone-identity-repaired*) ;; *) echo "FAIL: no repair notice: $OUT" >&2; exit 1;; esac
grep -q '^AGENT_ID=agent-w2-c1$' "${HOOK_CLONE}/.env.clone" || {
  echo "FAIL: hook did not repair identity" >&2; cat "${HOOK_CLONE}/.env.clone" >&2; exit 1; }
grep -q '^FRONTEND_PORT=5228$' "${HOOK_CLONE}/.env.clone" || {   # 5221 + (2*3+1)
  echo "FAIL: hook did not repair port" >&2; cat "${HOOK_CLONE}/.env.clone" >&2; exit 1; }

echo "-- silent when the clone already agrees"
OUT="$(printf '{"source":"startup","cwd":"%s"}' "$HOOK_CLONE" | HOME="$FAKE_HOME" python3 "$HOOK")"
[ -z "$OUT" ] || { echo "FAIL: expected silence, got: $OUT" >&2; exit 1; }

echo "-- no-op outside a clone layout"
OUT="$(printf '{"source":"startup","cwd":"%s"}' "$TMP" | HOME="$FAKE_HOME" python3 "$HOOK")"
[ -z "$OUT" ] || { echo "FAIL: expected silence outside a clone, got: $OUT" >&2; exit 1; }
[ -e "${TMP}/.env.clone" ] && { echo "FAIL: hook wrote outside a clone" >&2; exit 1; }

echo "-- ignores non-startup sources"
UNREG_CLONE="${TMP}/code/other-workspaces/other-w0/other-w0-c0"
mkdir -p "$UNREG_CLONE"
OUT="$(printf '{"source":"compact","cwd":"%s"}' "$HOOK_CLONE" | HOME="$FAKE_HOME" python3 "$HOOK")"
[ -z "$OUT" ] || { echo "FAIL: fired on compact: $OUT" >&2; exit 1; }

echo "-- never invents ports for an unregistered repo"
OUT="$(printf '{"source":"startup","cwd":"%s"}' "$UNREG_CLONE" | HOME="$FAKE_HOME" python3 "$HOOK")"
[ -z "$OUT" ] || { echo "FAIL: acted on unregistered repo: $OUT" >&2; exit 1; }
[ -e "${UNREG_CLONE}/.env.clone" ] && { echo "FAIL: wrote .env.clone for unregistered repo" >&2; exit 1; }

echo "-- survives malformed stdin"
OUT="$(printf 'not json' | HOME="$FAKE_HOME" python3 "$HOOK")"
[ -z "$OUT" ] || { echo "FAIL: output on malformed input: $OUT" >&2; exit 1; }

echo
echo "PASS: clone-identity"
