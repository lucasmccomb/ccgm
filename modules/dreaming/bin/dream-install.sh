#!/usr/bin/env bash
# CCGM dreaming — interactive installer (Epic 6).
#
# Detects the host platform, installs the daily scheduled job via the
# platform-abstracted helper (`sched_platform.install_scheduled_job`),
# ensures the dreaming state directory layout exists, and writes a default
# `config.json` if none is present. Mirrors
# modules/autoheal/bin/autoheal-install.sh's structure and rationale
# throughout; see that file's comments for the fuller "why" on the
# scoped-.env / shim-entrypoint pattern this reuses.
#
# Env overrides (tests):
#   CCGM_DREAMING_DIR        Root of dreaming state.
#   CCGM_DREAMING_USERNAME   Override the $USER value used for the
#                             LaunchAgent label (tests).
#   CCGM_DREAMING_HOUR       Hour of daily run (default 3).
#   CCGM_DREAMING_MINUTE     Minute (default 30).

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
HOUR="${CCGM_DREAMING_HOUR:-3}"
MINUTE="${CCGM_DREAMING_MINUTE:-30}"

mkdir -p \
    "${DREAMING_DIR}" \
    "${DREAMING_DIR}/proposals" \
    "${DREAMING_DIR}/digests" \
    "${DREAMING_DIR}/evals" \
    "${DREAMING_DIR}/state" \
    "${DREAMING_DIR}/state/runs" \
    "${HOME}/.claude/logs"

# ---------------------------------------------------------------------
# Scoped API-key env file.
#
# We deliberately do NOT source the user's shell rc (~/.zshrc etc.) at
# LaunchAgent fire time — putting ANTHROPIC_API_KEY in shell rc leaks it
# to every Anthropic SDK client running in the user's interactive shells
# (anthropic-python, claude CLI, etc.), which would bill against the API
# key instead of the Claude Max subscription.
#
# dream_analyze.py's own load_env() reads this file directly (falling back
# to ~/.claude/autoheal/.env when this one has no key set — §3.5 auth
# flow), so it is authoritative even without any shell-level sourcing.
# Mode 0600 keeps it out of other users' read paths on shared machines.
# Empty by default so a fresh install never accidentally enables billing.
# ---------------------------------------------------------------------

ENV_FILE="${DREAMING_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    cat >"${ENV_FILE}" <<'EOF'
# dreaming API keys — scoped to the dreaming LaunchAgent ONLY.
#
# Do NOT export these from ~/.zshrc / ~/.bash_profile / ~/.profile — the
# Anthropic SDK auto-picks up ANTHROPIC_API_KEY from env and would bill
# against the API key instead of your Claude Max subscription.
#
# Uncomment + populate to enable the nightly analyzer. An empty/missing
# key is fine — dream_analyze.py logs "ANTHROPIC_API_KEY not set;
# skipping" and the rest of the chain (digest, retention) still runs.
# Mode 0600 — owner read/write only. Falls back to
# ~/.claude/autoheal/.env if that module is also installed and configured.

# ANTHROPIC_API_KEY=sk-ant-...
EOF
    chmod 0600 "${ENV_FILE}"
    echo "dream-install: wrote scoped env template to ${ENV_FILE} (mode 0600)"
else
    chmod 0600 "${ENV_FILE}" 2>/dev/null || true
fi

# ---------------------------------------------------------------------
# Default config.json (§3.3 config keys — matches dream_analyze.py's
# DEFAULT_CONFIG plus the retention keys dream-daily.sh reads). Written
# only if missing — no prior version of this file exists to migrate.
# ---------------------------------------------------------------------

if [ ! -f "${DREAMING_DIR}/config.json" ]; then
    cat >"${DREAMING_DIR}/config.json" <<'EOF'
{
  "enabled": true,
  "map_model": "claude-sonnet-5",
  "reduce_model": "claude-opus-4-8",
  "max_input_tokens": 200000,
  "max_output_tokens": 4096,
  "daily_cost_cap_usd": 10.00,
  "lookback_days": 7,
  "auto_apply_counters": false,
  "promotion_min_sessions": 3,
  "promotion_min_agents": 2,
  "scopes": [],
  "cost_pricing": {},
  "retention_gzip_days": 30,
  "retention_delete_days": 60
}
EOF
    echo "dream-install: wrote default config to ${DREAMING_DIR}/config.json"
fi

# ---------------------------------------------------------------------
# Daily wrapper entrypoint.
#
# The launchd plist points at ~/.claude/dreaming/dream-daily.sh. That file
# is a thin shim that:
#   (a) sources ~/.claude/dreaming/.env for API keys — scoped to dreaming
#       only, NOT the user's interactive shell rc (redundant with
#       dream_analyze.py's own load_env(), kept for parity with autoheal's
#       shim and any future chain step that is less self-contained);
#   (b) execs the canonical module's full chain wrapper (analyze -> digest
#       -> reconcile -> auto-apply -> retention).
#
# Idempotent: writes the entrypoint if missing OR if the existing file is
# a stale shim (matched by header marker text).
# ---------------------------------------------------------------------

DAILY_PATH="${DREAMING_DIR}/dream-daily.sh"
DAILY_IS_STALE=0
if [ -f "${DAILY_PATH}" ]; then
    HEAD5="$(head -5 "${DAILY_PATH}" 2>/dev/null || true)"
    case "${HEAD5}" in
        *"dreaming daily entrypoint"*) ;;
        *) DAILY_IS_STALE=1 ;;
    esac
fi
if [ ! -f "${DAILY_PATH}" ] || [ "${DAILY_IS_STALE}" = "1" ]; then
    cat >"${DAILY_PATH}" <<'EOF'
#!/usr/bin/env bash
# dreaming daily entrypoint (called by launchd LaunchAgent).
#
# Sources ~/.claude/dreaming/.env for API keys (scoped to dreaming only —
# never via the user's shell rc). Then execs the module's full chain
# wrapper: analyze -> digest -> reconcile -> auto-apply -> retention.

ENV_FILE="${HOME}/.claude/dreaming/.env"
if [ -r "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
fi

CCGM_DREAMING_BIN="${CCGM_DREAMING_BIN:-${HOME}/code/ccgm/modules/dreaming/bin}"
exec "${CCGM_DREAMING_BIN}/dream-daily.sh"
EOF
    chmod +x "${DAILY_PATH}"
    echo "dream-install: wrote daily entrypoint to ${DAILY_PATH}"
fi

# ---------------------------------------------------------------------
# Scheduling via sched_platform.
# ---------------------------------------------------------------------

USERNAME="${CCGM_DREAMING_USERNAME:-${USER:-unknown}}"
LABEL="com.${USERNAME}.ccgm.dreaming.daily"

PLATFORM="$(python3 -c 'import platform; print(platform.system())')"

echo "dream-install: detected platform=${PLATFORM}"
echo "dream-install: scheduling label=${LABEL} hour=${HOUR} minute=${MINUTE}"

# Locate sched_platform.py — prefer the installed copy under ~/.claude/lib,
# fall back to the in-tree path for ad-hoc dev installs.
SCHED_LIB_DIR=""
for candidate in \
    "${HOME}/.claude/lib" \
    "$(cd "${MODULE_ROOT}/../hooks/lib" 2>/dev/null && pwd)"; do
    if [ -n "${candidate}" ] && [ -f "${candidate}/sched_platform.py" ]; then
        SCHED_LIB_DIR="${candidate}"
        break
    fi
done

if [ -z "${SCHED_LIB_DIR}" ]; then
    echo "dream-install: cannot locate sched_platform.py; install the hooks module first." >&2
    exit 1
fi

INSTALL_PY=$(cat <<PY
import sys

sys.path.insert(0, "${SCHED_LIB_DIR}")
import sched_platform

label = "${LABEL}"
command = "${DAILY_PATH}"
hour = ${HOUR}
minute = ${MINUTE}

try:
    sched_platform.install_scheduled_job(label, command, hour, minute)
    print(f"OK: installed {label}")
except NotImplementedError as exc:
    print(f"DEFERRED: {exc}", file=sys.stderr)
    sys.exit(0)
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
PY
)

python3 -c "${INSTALL_PY}"
RC=$?

if [ "${RC}" -ne 0 ]; then
    echo "dream-install: scheduling step failed (rc=${RC})" >&2
    exit "${RC}"
fi

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "dreaming install complete."
echo "  state dir:     ${DREAMING_DIR}"
echo "  config:        ${DREAMING_DIR}/config.json"
echo "  daily script:  ${DAILY_PATH}"
echo "  job label:     ${LABEL}"
echo "  schedule:      ${HOUR}:$(printf '%02d' "${MINUTE}") local"
echo ""
echo "Add an API key to ${ENV_FILE} (mode 0600) — NOT to ~/.zshrc."
echo "  ANTHROPIC_API_KEY=...   (analyzer; falls back to ~/.claude/autoheal/.env)"
echo ""
echo "auto_apply_counters stays false until you deliberately flip it in"
echo "  ${DREAMING_DIR}/config.json — see /dream for current status."
