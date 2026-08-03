#!/usr/bin/env bash
# test-paths-symlink.sh
#
# Epic 1 (issue #954, plan.md
# ~/code/plans/ccgm-dynamic-rule-injection/plan.md, Epic 1). Settles, on
# evidence that cannot be explained three ways, whether a SYMLINKED
# user-level rule carrying `paths:` frontmatter is loaded lazily on a
# matching file access -- replacing the original decisive experiment
# (research-e-orchestrator-firsthand.md, Finding E11), which had no
# control arm and a confounded positive arm, and asserted on the
# model's verbal self-report instead of a deterministic oracle.
#
# Five arms, all asserting on the InstructionsLoaded log (Epic 7's
# oracle -- lib/loaded_log.py), never on model output:
#
#   A - control    : no `paths:` frontmatter, no tools    -> must load
#   B - negative   : `paths:` scoped to **/*.xyzzy, no tools -> must NOT load
#   C - positive   : same scoping, session Reads a matching file only
#                    -> must load, AND the transcript must show no read
#                       of the canary rule file itself (rules out
#                       self-discovery)
#   D - write-trigger : same scoping, session WRITES a new matching
#                       file, never reads one -> RECORDED, not asserted
#   E - grep-trigger  : same scoping, session GREPs across matching
#                       files, never reads one -> RECORDED, not asserted
#
# Arms A+B+C together are the sound experiment: A rules out "nothing
# loads here", B rules out "loaded unconditionally", C rules out "the
# model found it itself".
#
# GATES (plan.md §7.5):
#   Gate 0 -- if arm A fails, the measurement apparatus itself is
#     broken. No conclusion may be drawn from ANY other arm, including
#     the original research finding. This script stops immediately
#     after arm A on failure and reports BLOCKED.
#   Gate 1 -- if arm C fails, Tier B is void but Tier C is unaffected.
#     This script keeps running (D and E still answer their own
#     independent questions) but reports BLOCKED for the epic.
#
# Needs an authenticated `claude` CLI and spends real (small, Haiku)
# API cost -- this belongs to the plan's model-in-the-loop gate
# (plan.md §8.4 Gate 2), NOT the per-PR deterministic gate. Do not wire
# this into .github/workflows/test.yml.
#
# MACHINE-GLOBAL STATE DISCIPLINE (plan.md §8.3, R21) -- non-negotiable:
#   - Every artifact this script writes into the operator's real
#     ~/.claude/rules/ is named with a PID-unique "zzz-ccgm-test-$$-"
#     prefix.
#   - A machine-wide lock (~/.claude/.ccgm-rule-test.lock, mkdir-based
#     -- `flock` is not available on stock macOS bash 3.2/BSD userland,
#     so a mkdir lock is this script's `flock`-style equivalent: mkdir
#     is atomic across POSIX filesystems, fails loudly with EEXIST on
#     contention, and this script polls it with a bounded timeout and a
#     named error) is acquired before the first write and released in
#     a `trap ... EXIT`, so a second concurrent invocation on this
#     machine waits rather than racing on ~/.claude/rules/.
#   - Every symlink is removed the moment its arm finishes, and the
#     trap sweeps any leftovers by the PID-unique prefix as a backstop.
#   - ~/.claude/rules/'s exact pre-run file list is asserted to be
#     restored afterwards; a mismatch fails loudly rather than silently.
#   - Cleanup of temp directories uses `python3 -c "import shutil;
#     shutil.rmtree(...)"`, never `rm -rf`, per plan.md's own guidance
#     (mktemp -d lands under /var/folders on macOS, and `rm -rf
#     /var/...` trips CCGM's own destructive-pattern guard).
#
# Run: bash modules/relevance-injection/tests/test-paths-symlink.sh
#
# Requires: an authenticated `claude` CLI (2.1.220+) on PATH, network
# access, and a small amount of real API spend (Haiku, capped per call
# via --max-budget-usd). Five short claude -p calls; typical run cost
# observed during development was well under $1 total.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK_SCRIPT="${MODULE_ROOT}/hooks/instructions-loaded-log.py"
export LOADED_LOG_LIB="${MODULE_ROOT}/lib"
ARM_CHECK_PY="${SCRIPT_DIR}/fixtures/arm_check.py"

PASS=0
FAIL=0
BLOCKED_REASONS=()

RULES_DIR="${HOME}/.claude/rules"
LOCK_DIR="${HOME}/.claude/.ccgm-rule-test.lock"
LOCK_MAIN_TIMEOUT_SECS=120
LOCK_HELD=0
PID_PREFIX="zzz-ccgm-test-$$-"

TMP_ROOT=""
PRE_RUN_LISTING=""
CLEANUP_RAN=0

# --- reporting helpers -------------------------------------------------

pass_msg() {
  PASS=$((PASS + 1))
  echo "PASS: $1"
}

fail_msg() {
  FAIL=$((FAIL + 1))
  echo "FAIL: $1"
}

record_msg() {
  echo "RECORDED: $1"
}

# --- machine-wide lock (mkdir-based; see header comment) ---------------

# Break a lock whose recorded holder is no longer running.
#
# This is the one property a mkdir-based lock does NOT inherit from real
# flock: flock lives on the holder's open file descriptor, so the kernel
# releases it when the process dies for any reason, SIGKILL included. A
# directory has no such teardown -- without this check, one `kill -9`
# while the lock is held would deadlock every future run of this suite
# until a human removed the directory by hand.
#
# Only ever breaks a lock we can PROVE is dead: `kill -0` must report the
# recorded pid as gone. An unreadable, empty, or non-numeric holder.pid
# is treated as live, so a lock caught mid-write (directory created, pid
# not yet recorded) is never stolen from a running holder.
break_stale_lock() {
  [ -d "${LOCK_DIR}" ] || return 1
  local holder
  holder="$(cat "${LOCK_DIR}/holder.pid" 2>/dev/null || true)"
  case "${holder}" in
    ''|*[!0-9]*) return 1 ;;   # absent or non-numeric -- assume live
  esac
  if kill -0 "${holder}" 2>/dev/null; then
    return 1                    # holder is alive; genuine contention
  fi
  echo "NOTE: breaking stale lock ${LOCK_DIR} (holder pid ${holder} is gone)" >&2
  rm -f "${LOCK_DIR}/holder.pid" 2>/dev/null
  rmdir "${LOCK_DIR}" 2>/dev/null
  return 0
}

acquire_lock() {
  # args: timeout_secs
  local timeout_secs="$1"
  local waited=0
  while true; do
    if mkdir "${LOCK_DIR}" 2>/dev/null; then
      echo "$$" > "${LOCK_DIR}/holder.pid" 2>/dev/null
      return 0
    fi
    # Retry immediately if the blocker turned out to be a dead holder.
    if break_stale_lock; then
      continue
    fi
    if [ "${waited}" -ge "${timeout_secs}" ]; then
      local holder
      holder="$(cat "${LOCK_DIR}/holder.pid" 2>/dev/null || echo unknown)"
      echo "ERROR: lock contention -- ${LOCK_DIR} still held (holder pid: ${holder}) after ${timeout_secs}s" >&2
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
}

release_lock() {
  rm -f "${LOCK_DIR}/holder.pid" 2>/dev/null
  rmdir "${LOCK_DIR}" 2>/dev/null
}

# --- cleanup (registered via trap ... EXIT before any write happens) ---

cleanup() {
  [ "${CLEANUP_RAN}" -eq 1 ] && return
  CLEANUP_RAN=1

  # Sweep every symlink this PID could have created, as a backstop --
  # each arm already removes its own symlink right after it runs.
  local leftover
  for leftover in "${RULES_DIR}/${PID_PREFIX}"*; do
    [ -e "${leftover}" ] || [ -L "${leftover}" ] || continue
    rm -f "${leftover}"
  done

  if [ -n "${TMP_ROOT}" ] && [ -d "${TMP_ROOT}" ]; then
    python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "${TMP_ROOT}"
  fi

  if [ "${LOCK_HELD}" -eq 1 ]; then
    release_lock
    LOCK_HELD=0
  fi

  # Assert ~/.claude/rules/ is back to its exact pre-run file list.
  if [ -n "${PRE_RUN_LISTING+set}" ]; then
    local post_listing
    post_listing="$(ls -1 "${RULES_DIR}" 2>/dev/null | sort)"
    if [ "${post_listing}" != "${PRE_RUN_LISTING}" ]; then
      echo "FAIL: ~/.claude/rules/ is NOT back to its exact pre-run file list" >&2
      echo "--- pre-run ---" >&2
      printf '%s\n' "${PRE_RUN_LISTING}" >&2
      echo "--- post-run ---" >&2
      printf '%s\n' "${post_listing}" >&2
      FAIL=$((FAIL + 1))
    else
      pass_msg "~/.claude/rules/ restored to its exact pre-run file list"
    fi
  fi
}
trap cleanup EXIT

# --- preconditions ------------------------------------------------------

if ! command -v claude >/dev/null 2>&1; then
  echo "BLOCKED: no 'claude' CLI on PATH -- this suite requires an authenticated" >&2
  echo "  Claude Code CLI and belongs to the model-in-the-loop gate (plan.md §8.4" >&2
  echo "  Gate 2), not the per-PR deterministic gate." >&2
  exit 1
fi

if [ ! -d "${RULES_DIR}" ]; then
  echo "BLOCKED: ${RULES_DIR} does not exist -- nothing to symlink into." >&2
  exit 1
fi

echo "=== Epic 1: paths: frontmatter controlled experiment (issue #954) ==="
echo "claude CLI: $(command -v claude)"
echo "claude --version: $(claude --version 2>&1 | head -1)"
echo ""

# --- lock contention self-test (proves "waits, not races") -------------
#
# Acquires the real lock first, then -- while still holding it -- spawns
# a background attempt with a short timeout and confirms it blocks for
# (approximately) the full timeout rather than racing straight through.
# The background attempt never succeeds in mkdir'ing (the real lock is
# held), so it never touches ~/.claude/.ccgm-rule-test.lock itself.

echo "--- Lock contention self-test ---"
if ! acquire_lock "${LOCK_MAIN_TIMEOUT_SECS}"; then
  exit 1
fi
LOCK_HELD=1

CONTENTION_TIMEOUT=3
# Pre-allocate the result path BEFORE backgrounding and reference this
# same variable from both sides. `$$` is not usable for this: inside a
# `( ... ) &` subshell it still expands to the TOP-LEVEL script's PID
# (bash caches $$ at shell startup and subshells inherit that cached
# value, not their own forked PID), while `$!` after backgrounding
# yields the subshell's real, DIFFERENT PID -- so writer and reader
# would disagree on the filename. A path fixed by value before the
# fork sidesteps the mismatch entirely.
contention_result_file="$(mktemp -t ccgm-lock-selftest)"
contention_start=$(date +%s)
(
  # Re-declare a private copy of acquire_lock's mkdir loop rather than
  # calling the parent's function, so this subshell can never mutate
  # LOCK_HELD in a way that would be visible to (or confused with) the
  # parent's own state.
  waited=0
  while true; do
    if mkdir "${LOCK_DIR}" 2>/dev/null; then
      echo "acquired" > "${contention_result_file}"
      rmdir "${LOCK_DIR}" 2>/dev/null
      exit 0
    fi
    if [ "${waited}" -ge "${CONTENTION_TIMEOUT}" ]; then
      echo "timed-out" > "${contention_result_file}"
      exit 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
) &
contention_pid=$!
wait "${contention_pid}"
contention_end=$(date +%s)
contention_elapsed=$((contention_end - contention_start))
contention_result="$(cat "${contention_result_file}" 2>/dev/null)"
[ -z "${contention_result}" ] && contention_result="missing"
rm -f "${contention_result_file}" 2>/dev/null

if [ "${contention_result}" = "timed-out" ] && [ "${contention_elapsed}" -ge "${CONTENTION_TIMEOUT}" ]; then
  pass_msg "second concurrent lock attempt waited ${contention_elapsed}s then timed out (did not race)"
else
  fail_msg "lock contention self-test: expected 'timed-out' after >=${CONTENTION_TIMEOUT}s, got '${contention_result}' after ${contention_elapsed}s"
fi
echo ""

# --- pre-run snapshot (checked in cleanup(), above) ---------------------

PRE_RUN_LISTING="$(ls -1 "${RULES_DIR}" 2>/dev/null | sort)"

TMP_ROOT="$(mktemp -d)"

# --- per-arm helpers -----------------------------------------------------

# Sets globals: ARM_DIR, ARM_REAL_PATH, ARM_SYMLINK_PATH
arm_setup() {
  local arm_id="$1"
  local rule_body_file="$2"  # path to a file already containing the canary body

  ARM_DIR="${TMP_ROOT}/arm-${arm_id}"
  mkdir -p "${ARM_DIR}/src" "${ARM_DIR}/scratch/.claude" "${ARM_DIR}/log"

  local src_file="${ARM_DIR}/src/${PID_PREFIX}arm-${arm_id}.md"
  cp "${rule_body_file}" "${src_file}"

  ARM_SYMLINK_PATH="${RULES_DIR}/${PID_PREFIX}arm-${arm_id}.md"
  ln -s "${src_file}" "${ARM_SYMLINK_PATH}"

  # Claude Code reports the RESOLVED symlink target as file_path, not
  # the ~/.claude/rules/ symlink path itself (confirmed empirically and
  # recorded in decisions.md) -- so this is what assert_loaded() must
  # be compared against.
  ARM_REAL_PATH="$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${src_file}")"

  cat > "${ARM_DIR}/scratch/.claude/settings.json" <<SETTINGSEOF
{
  "hooks": {
    "InstructionsLoaded": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "CCGM_RULE_LOADING_DIR=${ARM_DIR}/log python3 ${HOOK_SCRIPT}",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
SETTINGSEOF
}

arm_remove_symlink() {
  rm -f "${ARM_SYMLINK_PATH}"
}

# Runs `claude -p` in the arm's scratch dir with a wall-clock watchdog
# (portable bash 3.2 pattern -- no dependency on GNU `timeout`/`gtimeout`,
# neither of which is guaranteed present on stock macOS).
#
# --verbose is REQUIRED here, not optional. `--output-format json` alone
# emits exactly one `type: "result"` object; the full per-turn message
# array (including `assistant` messages with `tool_use` blocks, which
# arm C's self-discovery check in arm_check.py depends on) is only
# emitted when verbose mode is on. Confirmed empirically on this CLI
# (2.1.220): identical `claude -p --output-format json` invocations
# produced a bare `result` dict when the effective verbose setting was
# false, and the full message array once `--verbose` forced it true --
# regardless of the operator's own ~/.claude/settings.json "verbose"
# value, which must NOT be what makes this deterministic across
# machines.
#
# args: arm_id, prompt, tools_csv
arm_run_claude() {
  local arm_id="$1" prompt="$2" tools="$3"
  local watchdog_timeout=90

  (
    cd "${ARM_DIR}/scratch" || exit 1
    claude -p "${prompt}" \
      --model haiku \
      --output-format json \
      --verbose \
      --permission-mode bypassPermissions \
      --tools "${tools}" \
      --strict-mcp-config \
      --no-session-persistence \
      --max-budget-usd 1 \
      > "${ARM_DIR}/out.json" 2> "${ARM_DIR}/err.txt"
  ) &
  local cmd_pid=$!

  (
    sleep "${watchdog_timeout}"
    kill -TERM "${cmd_pid}" 2>/dev/null
  ) &
  local watchdog_pid=$!

  wait "${cmd_pid}" 2>/dev/null
  local status=$?
  kill "${watchdog_pid}" 2>/dev/null
  wait "${watchdog_pid}" 2>/dev/null

  if [ "${status}" -ne 0 ]; then
    echo "  (note: arm ${arm_id}'s claude -p exited ${status} -- see ${ARM_DIR}/err.txt)"
  fi
  return "${status}"
}

# Prints LOADED / NOT_LOADED / LOG_MISSING
arm_check_loaded() {
  python3 "${ARM_CHECK_PY}" check-loaded "${ARM_DIR}/log" "${ARM_REAL_PATH}"
}

# Prints OK / SELF_READ_DETECTED: <path> / CHECK_ERROR: <detail>
arm_check_no_self_read() {
  local basename
  basename="$(basename "${ARM_REAL_PATH}")"
  python3 "${ARM_CHECK_PY}" check-no-self-read "${ARM_DIR}/out.json" "${ARM_REAL_PATH}" "${basename}"
}

# --- canary bodies -------------------------------------------------------

UNSCOPED_BODY="${TMP_ROOT}/unscoped-body.md"
cat > "${UNSCOPED_BODY}" <<'BODYEOF'
This is the Epic 1 control canary. It carries no paths: frontmatter and
must always load in every session -- proving the InstructionsLoaded
oracle actually detects a loaded rule at all (Gate 0, plan.md §7.5).
BODYEOF

SCOPED_BODY="${TMP_ROOT}/scoped-body.md"
cat > "${SCOPED_BODY}" <<'BODYEOF'
---
paths:
  - "**/*.xyzzy"
---
This is an Epic 1 canary scoped to *.xyzzy files. It must NOT load
unless a matching file is read (or, per arms D/E, possibly written or
grepped -- that is the open question those arms answer).
BODYEOF

# =========================================================================
# Arm A -- control: no frontmatter, no tools -> must load
# =========================================================================
echo "--- Arm A (control) ---"
arm_setup "a" "${UNSCOPED_BODY}"
arm_run_claude "a" "Reply with the single word done. Do not use any tools." ""
arm_a_result="$(arm_check_loaded)"
arm_remove_symlink
echo "  result: ${arm_a_result}"

if [ "${arm_a_result}" = "LOADED" ]; then
  pass_msg "arm A (control): unscoped canary IS loaded with no tools"
else
  fail_msg "arm A (control): expected LOADED, got ${arm_a_result} -- the measurement apparatus is broken"
  BLOCKED_REASONS+=("Gate 0: arm A (control) failed (${arm_a_result}) -- no conclusion may be drawn from any other arm, per plan.md §7.5 Gate 0.")
  echo ""
  echo "=== BLOCKED: Gate 0 (arm A control) failed. Stopping -- arms B-E would be uninterpretable. ==="
  for reason in "${BLOCKED_REASONS[@]}"; do
    echo "  - ${reason}"
  done
  exit 1
fi
echo ""

# =========================================================================
# Arm B -- negative: scoped, no tools -> must NOT load
# =========================================================================
echo "--- Arm B (negative) ---"
arm_setup "b" "${SCOPED_BODY}"
arm_run_claude "b" "Reply with the single word done. Do not use any tools." ""
arm_b_result="$(arm_check_loaded)"
arm_remove_symlink
echo "  result: ${arm_b_result}"

if [ "${arm_b_result}" = "NOT_LOADED" ]; then
  pass_msg "arm B (negative): scoped canary is NOT loaded with no matching file access"
else
  fail_msg "arm B (negative): expected NOT_LOADED, got ${arm_b_result}"
fi
echo ""

# =========================================================================
# Arm C -- positive: scoped, Read a matching file only -> must load,
# AND the transcript must show no read of the canary rule itself.
# =========================================================================
echo "--- Arm C (positive) ---"
arm_setup "c" "${SCOPED_BODY}"
echo "trigger content, nothing special" > "${ARM_DIR}/scratch/trigger.xyzzy"
arm_run_claude "c" "Read the file trigger.xyzzy and then reply with the word done. Do not read any other files." "Read"
arm_c_result="$(arm_check_loaded)"
arm_c_self_read="$(arm_check_no_self_read)"
arm_remove_symlink
echo "  loaded result: ${arm_c_result}"
echo "  self-discovery check: ${arm_c_self_read}"

arm_c_ok=1
if [ "${arm_c_result}" = "LOADED" ]; then
  pass_msg "arm C (positive): scoped canary IS loaded after reading a matching file"
else
  fail_msg "arm C (positive): expected LOADED, got ${arm_c_result}"
  arm_c_ok=0
fi
if [ "${arm_c_self_read}" = "OK" ]; then
  pass_msg "arm C (positive): transcript shows no read of the canary rule file itself (rules out self-discovery)"
else
  fail_msg "arm C (positive): self-discovery check failed: ${arm_c_self_read}"
  arm_c_ok=0
fi

if [ "${arm_c_ok}" -eq 0 ]; then
  BLOCKED_REASONS+=("Gate 1: arm C (positive) failed -- Tier B is void, Tier C is unaffected, per plan.md §7.5 Gate 1. loaded=${arm_c_result} self-discovery=${arm_c_self_read}")
fi
echo ""

# =========================================================================
# Arm D -- write-trigger: scoped, Write a NEW matching file, never Read
# one -> RECORDED, no pass/fail (plan.md R20 -- nobody has asked this
# question before; §3.1 says the glob matches files Claude "reads").
# =========================================================================
echo "--- Arm D (write-trigger) ---"
arm_setup "d" "${SCOPED_BODY}"
arm_run_claude "d" "Create a new file named new.xyzzy containing the text hello. Do not read any files. Then reply with the word done." "Write"
arm_d_result="$(arm_check_loaded)"
arm_remove_symlink
echo "  result: ${arm_d_result}"
record_msg "arm D (write-trigger): ${arm_d_result}"
if [ "${arm_d_result}" = "LOG_MISSING" ]; then
  fail_msg "arm D (write-trigger): harness produced no InstructionsLoaded log at all -- inconclusive, not a valid recorded answer"
else
  pass_msg "arm D (write-trigger): produced a valid recorded answer (${arm_d_result})"
fi
echo ""

# =========================================================================
# Arm E -- grep-trigger: scoped, Grep across matching files, never Read
# one -> RECORDED, no pass/fail.
# =========================================================================
echo "--- Arm E (grep-trigger) ---"
arm_setup "e" "${SCOPED_BODY}"
echo "needle-value-here" > "${ARM_DIR}/scratch/haystack.xyzzy"
arm_run_claude "e" "Use Grep to search for the pattern needle-value-here across all .xyzzy files in the current directory. Do not use the Read tool. Then reply with the word done." "Grep"
arm_e_result="$(arm_check_loaded)"
arm_remove_symlink
echo "  result: ${arm_e_result}"
record_msg "arm E (grep-trigger): ${arm_e_result}"
if [ "${arm_e_result}" = "LOG_MISSING" ]; then
  fail_msg "arm E (grep-trigger): harness produced no InstructionsLoaded log at all -- inconclusive, not a valid recorded answer"
else
  pass_msg "arm E (grep-trigger): produced a valid recorded answer (${arm_e_result})"
fi
echo ""

# --- summary --------------------------------------------------------------

echo "=== Summary ==="
echo "  arm A (control):        ${arm_a_result}"
echo "  arm B (negative):       ${arm_b_result}"
echo "  arm C (positive):       loaded=${arm_c_result} self-discovery=${arm_c_self_read}"
echo "  arm D (write-trigger):  ${arm_d_result}  (recorded, not asserted)"
echo "  arm E (grep-trigger):   ${arm_e_result}  (recorded, not asserted)"
echo ""
echo "  PASS: ${PASS}  FAIL: ${FAIL}"

if [ "${#BLOCKED_REASONS[@]}" -gt 0 ]; then
  echo ""
  echo "=== BLOCKED ==="
  for reason in "${BLOCKED_REASONS[@]}"; do
    echo "  - ${reason}"
  done
  exit 1
fi

if [ "${FAIL}" -gt 0 ]; then
  exit 1
fi

exit 0
