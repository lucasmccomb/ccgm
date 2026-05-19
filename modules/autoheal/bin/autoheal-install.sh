#!/usr/bin/env bash
# CCGM autoheal — interactive installer (Epic 6).
#
# Detects the host platform, installs the daily scheduled job via the
# platform-abstracted helper (`sched_platform.install_scheduled_job`),
# ensures the autoheal state directory layout exists, and writes a
# default `config.json` if none is present.
#
# Env overrides (tests):
#   CCGM_AUTOHEAL_DIR        Root of autoheal state.
#   CCGM_AUTOHEAL_USERNAME   Override the $USER value used for the
#                             LaunchAgent label (tests).
#   CCGM_AUTOHEAL_HOUR       Hour of daily run (default 9).
#   CCGM_AUTOHEAL_MINUTE     Minute (default 0).

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
HOUR="${CCGM_AUTOHEAL_HOUR:-9}"
MINUTE="${CCGM_AUTOHEAL_MINUTE:-0}"

mkdir -p \
    "${AUTOHEAL_DIR}" \
    "${AUTOHEAL_DIR}/events" \
    "${AUTOHEAL_DIR}/proposals" \
    "${AUTOHEAL_DIR}/applied" \
    "${AUTOHEAL_DIR}/sent" \
    "${HOME}/.claude/logs"

# Default snoozed.json so the lookup never fails-open.
if [ ! -f "${AUTOHEAL_DIR}/snoozed.json" ]; then
    printf '{}\n' > "${AUTOHEAL_DIR}/snoozed.json"
fi

# ---------------------------------------------------------------------
# Scoped API-key env file.
#
# We deliberately do NOT source the user's shell rc (~/.zshrc etc.)
# at LaunchAgent fire time — putting ANTHROPIC_API_KEY in shell rc
# leaks it to every Anthropic SDK client running in the user's
# interactive shells (anthropic-python, claude CLI, etc.) which would
# bill against the API key instead of the Claude Max subscription.
#
# Instead, the daily entrypoint sources THIS file. Mode 0600 keeps it
# out of other users' read paths on shared machines. Empty by default
# so a fresh install never accidentally enables billing.
# ---------------------------------------------------------------------

ENV_FILE="${AUTOHEAL_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    cat > "${ENV_FILE}" <<'EOF'
# autoheal API keys — scoped to the autoheal LaunchAgent ONLY.
#
# Do NOT export these from ~/.zshrc / ~/.bash_profile / ~/.profile —
# the Anthropic SDK auto-picks up ANTHROPIC_API_KEY from env and would
# bill against the API key instead of your Claude Max subscription.
#
# Uncomment + populate the keys you want autoheal to use. Empty values
# mean the corresponding step (analyzer / email) skips with a clean
# log entry. Mode 0600 — owner read/write only.

# ANTHROPIC_API_KEY=sk-ant-...
# RESEND_API_KEY=re_...
EOF
    chmod 0600 "${ENV_FILE}"
    echo "autoheal-install: wrote scoped env template to ${ENV_FILE} (mode 0600)"
else
    # Tighten permissions on an existing file if they are loose. We do
    # not touch the contents — those are user-authored.
    chmod 0600 "${ENV_FILE}" 2>/dev/null || true
fi

# ---------------------------------------------------------------------
# Default config.json.
#
# `webhook_token` is a 32-hex random — present so a future
# `dev.lem.work` integration only needs the URL set. All feature flags
# default OFF so installing the module never silently changes user
# behavior.
# ---------------------------------------------------------------------

if [ ! -f "${AUTOHEAL_DIR}/config.json" ]; then
    WEBHOOK_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
    cat > "${AUTOHEAL_DIR}/config.json" <<EOF
{
  "email_enabled": false,
  "realtime_alerts_enabled": false,
  "auto_apply_enabled": false,
  "digest_email": null,
  "webhook_url": null,
  "webhook_token": "${WEBHOOK_TOKEN}",
  "webhook_kinds": ["proposal", "event", "digest"],
  "webhook_max_per_run": 100,
  "model": "claude-sonnet-4-6",
  "default_model": "claude-sonnet-4-6",
  "cost_pricing": {
    "claude-sonnet-4-6":  {"input_per_million": 3,    "output_per_million": 15},
    "claude-opus-4-7":    {"input_per_million": 15,   "output_per_million": 75},
    "claude-haiku-4-5":   {"input_per_million": 0.80, "output_per_million": 4}
  },
  "max_input_tokens": 200000,
  "daily_cost_cap_usd": 1.00,
  "retention_gzip_days": 30,
  "retention_delete_days": 60
}
EOF
    echo "autoheal-install: wrote default config to ${AUTOHEAL_DIR}/config.json"
else
    # Idempotent merge: ensure cost_pricing + default_model exist in an
    # already-installed config without clobbering user customizations.
    python3 - "${AUTOHEAL_DIR}/config.json" <<'PY'
import json
import sys

path = sys.argv[1]

DEFAULT_PRICING = {
    "claude-sonnet-4-6":  {"input_per_million": 3,    "output_per_million": 15},
    "claude-opus-4-7":    {"input_per_million": 15,   "output_per_million": 75},
    "claude-haiku-4-5":   {"input_per_million": 0.80, "output_per_million": 4},
}

try:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, json.JSONDecodeError):
    sys.exit(0)

if not isinstance(cfg, dict):
    sys.exit(0)

dirty = False
if "cost_pricing" not in cfg or not isinstance(cfg.get("cost_pricing"), dict):
    cfg["cost_pricing"] = DEFAULT_PRICING
    dirty = True
if "default_model" not in cfg:
    cfg["default_model"] = cfg.get("model", "claude-sonnet-4-6")
    dirty = True
# Issue #517: backfill the new max_input_tokens key without overriding
# a value the user has already chosen.
if "max_input_tokens" not in cfg:
    cfg["max_input_tokens"] = 200000
    dirty = True
# Issue #517: bump default cost cap from $0.50 to $1.00, but only when
# the existing value is the legacy default (don't silently rewrite a
# user-customized cap).
if cfg.get("daily_cost_cap_usd") in (0.5, 0.50):
    cfg["daily_cost_cap_usd"] = 1.00
    dirty = True

if dirty:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"autoheal-install: merged cost_pricing/default_model/max_input_tokens into {path}")
PY
fi

# ---------------------------------------------------------------------
# Daily wrapper script entrypoint.
#
# The launchd plist points at ~/.claude/autoheal/autoheal-daily.sh.
# That file is a thin entrypoint that:
#   (a) sources ~/.claude/autoheal/.env for API keys — scoped to
#       autoheal only, NOT the user's interactive shell rc (which
#       would bill against the API key for every SDK client)
#   (b) execs the canonical module's full chain wrapper (analyze ->
#       auto-apply -> digest -> email -> publish -> retention)
#
# Idempotent: writes the entrypoint if missing OR if the existing file
# is a stale shim (matched by header marker text — both the Epic 6 stub
# and the pre-#513 rc-sourcing variant).
# ---------------------------------------------------------------------

DAILY_PATH="${AUTOHEAL_DIR}/autoheal-daily.sh"
DAILY_IS_STALE=0
if [ -f "${DAILY_PATH}" ]; then
    HEAD3="$(head -5 "${DAILY_PATH}" 2>/dev/null || true)"
    case "${HEAD3}" in
        *"Epic 6 install shim"*|*"rc so RESEND_API_KEY"*)
            DAILY_IS_STALE=1
            ;;
    esac
fi
if [ ! -f "${DAILY_PATH}" ] || [ "${DAILY_IS_STALE}" = "1" ]; then
    cat > "${DAILY_PATH}" <<'EOF'
#!/usr/bin/env bash
# autoheal daily entrypoint (called by launchd LaunchAgent).
#
# Sources ~/.claude/autoheal/.env for API keys (scoped to autoheal
# only — never via the user's shell rc, which would leak the key to
# every Anthropic SDK client and bill against the API key instead of
# the Claude Max subscription). Then execs the module's full chain
# wrapper: analyze -> auto-apply -> digest -> email -> publish ->
# retention.

ENV_FILE="${HOME}/.claude/autoheal/.env"
if [ -r "${ENV_FILE}" ]; then
    # `set -a` exports every variable defined in the sourced file.
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
fi

CCGM_AUTOHEAL_BIN="${CCGM_AUTOHEAL_BIN:-${HOME}/code/ccgm/modules/autoheal/bin}"
exec "${CCGM_AUTOHEAL_BIN}/autoheal-daily.sh"
EOF
    chmod +x "${DAILY_PATH}"
    echo "autoheal-install: wrote daily entrypoint to ${DAILY_PATH}"
fi

# Symlink the analyzer into ~/.claude/autoheal/ so the shim above can
# find it without knowing the canonical clone path. We use the canonical
# CCGM install location under ~/.claude/bin/autoheal-analyze.sh when
# CCGM has already symlinked the module's bin/ scripts; fall back to a
# direct copy from the module root for ad-hoc local installs.
ANALYZER_SRC=""
for candidate in \
    "${HOME}/.claude/bin/autoheal-analyze.sh" \
    "${MODULE_ROOT}/bin/autoheal-analyze.sh"; do
    if [ -f "${candidate}" ]; then
        ANALYZER_SRC="${candidate}"
        break
    fi
done

if [ -n "${ANALYZER_SRC}" ]; then
    ANALYZER_DST="${AUTOHEAL_DIR}/autoheal-analyze.sh"
    # Replace existing link/file to keep the daily wrapper in sync with
    # the canonical analyzer source.
    rm -f "${ANALYZER_DST}"
    ln -s "${ANALYZER_SRC}" "${ANALYZER_DST}" 2>/dev/null || cp "${ANALYZER_SRC}" "${ANALYZER_DST}"
    chmod +x "${ANALYZER_DST}" 2>/dev/null || true
fi

# ---------------------------------------------------------------------
# Scheduling via sched_platform.
# ---------------------------------------------------------------------

USERNAME="${CCGM_AUTOHEAL_USERNAME:-${USER:-unknown}}"
LABEL="com.${USERNAME}.ccgm.autoheal.daily"

# Detect platform via Python so we get the same answer the helper does.
PLATFORM="$(python3 -c 'import platform; print(platform.system())')"

echo "autoheal-install: detected platform=${PLATFORM}"
echo "autoheal-install: scheduling label=${LABEL} hour=${HOUR} minute=${MINUTE}"

# Locate sched_platform.py — prefer the installed copy under
# ~/.claude/lib, fall back to the in-tree path for ad-hoc dev installs.
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
    echo "autoheal-install: cannot locate sched_platform.py; install the hooks module first." >&2
    exit 1
fi

INSTALL_PY=$(cat <<PY
import os
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
    # Friendly message about Linux v2 — see lib/autoheal.cron.template.
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
    echo "autoheal-install: scheduling step failed (rc=${RC})" >&2
    exit "${RC}"
fi

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "autoheal install complete."
echo "  state dir:     ${AUTOHEAL_DIR}"
echo "  config:        ${AUTOHEAL_DIR}/config.json"
echo "  daily script:  ${DAILY_PATH}"
echo "  job label:     ${LABEL}"
echo "  schedule:      ${HOUR}:$(printf '%02d' "${MINUTE}") local"
echo ""
echo "Add API keys to ${ENV_FILE} (mode 0600) — NOT to ~/.zshrc."
echo "  ANTHROPIC_API_KEY=...   (analyzer)"
echo "  RESEND_API_KEY=...      (email digest, only if email_enabled=true)"
echo "Why not shell rc: anthropic-python / claude CLI auto-pick up the key"
echo "  and would bill against the API key instead of Claude Max."
echo ""
echo "Toggle features via /autoheal-toggle realtime|autoapply|email|webhook."
