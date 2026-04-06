#!/usr/bin/env bash
# auto-shutdown.sh — Auto-shutdown script that runs ON the VM (not the orchestrator).
#
# Installed as a cron job on the VM (every 5 minutes):
#   */5 * * * * /opt/ccgm/auto-shutdown.sh >> /var/log/ccgm-shutdown.log 2>&1
#
# Behavior:
#   1. If any agent tmux sessions are still active, record the time and exit.
#   2. If no sessions have been active for 15+ minutes, initiate shutdown.
#   3. If MAX_HOURS wall-clock time has been exceeded, kill all agents and shut down.
#
# Environment variables (read from /etc/ccgm/env if present):
#   MAX_HOURS    Maximum wall-clock hours before forced shutdown (default: 8)
#   IDLE_MINUTES Minutes of no active sessions before idle shutdown (default: 15)
#
# State files (on the VM):
#   /var/lib/ccgm/last-active   Timestamp of last observed active session (epoch seconds)
#   /var/lib/ccgm/vm-start      Timestamp of VM start / script first run (epoch seconds)
#   /var/log/ccgm-shutdown.log  Shutdown reason and timing (written by this script)
#
# Install in the golden image or via workspace-setup.sh:
#   install -m 0755 auto-shutdown.sh /opt/ccgm/auto-shutdown.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_HOURS="${MAX_HOURS:-8}"
IDLE_MINUTES="${IDLE_MINUTES:-15}"

STATE_DIR="/var/lib/ccgm"
LAST_ACTIVE_FILE="${STATE_DIR}/last-active"
VM_START_FILE="${STATE_DIR}/vm-start"
SHUTDOWN_LOG="/var/log/ccgm-shutdown.log"
ENV_FILE="/etc/ccgm/env"

# ---------------------------------------------------------------------------
# Logging (to shutdown log only - stdout is redirected there by cron)
# ---------------------------------------------------------------------------
log() {
  echo "$(date '+%Y-%m-%dT%H:%M:%S') [auto-shutdown] $*"
}

# ---------------------------------------------------------------------------
# Load optional env overrides
# ---------------------------------------------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
fi

# ---------------------------------------------------------------------------
# Ensure state directory exists
# ---------------------------------------------------------------------------
mkdir -p "${STATE_DIR}"

NOW=$(date +%s)

# ---------------------------------------------------------------------------
# Record VM start time on first run
# ---------------------------------------------------------------------------
if [[ ! -f "${VM_START_FILE}" ]]; then
  echo "${NOW}" > "${VM_START_FILE}"
  log "VM start time recorded: ${NOW}"
fi

VM_START=$(cat "${VM_START_FILE}")
WALL_CLOCK_SECS=$(( NOW - VM_START ))
WALL_CLOCK_HOURS=$(( WALL_CLOCK_SECS / 3600 ))

# ---------------------------------------------------------------------------
# Check wall-clock cap first (hard limit)
# ---------------------------------------------------------------------------
MAX_SECS=$(( MAX_HOURS * 3600 ))
if [[ "${WALL_CLOCK_SECS}" -ge "${MAX_SECS}" ]]; then
  log "SHUTDOWN: wall-clock limit reached (${WALL_CLOCK_HOURS}h >= ${MAX_HOURS}h limit)"
  log "Killing all agent tmux sessions..."

  # Kill all agent-N tmux sessions
  for i in 0 1 2 3; do
    agent_user="agent-${i}"
    if id "${agent_user}" &>/dev/null; then
      su - "${agent_user}" -c "tmux kill-server 2>/dev/null || true" 2>/dev/null || true
      echo "AGENT_TIMEOUT" > "/home/${agent_user}/status" || true
      chown "${agent_user}:${agent_user}" "/home/${agent_user}/status" 2>/dev/null || true
    fi
  done

  log "SHUTDOWN: initiating poweroff (reason: max-hours)"
  echo "shutdown" > "${SHUTDOWN_LOG}.reason"
  /sbin/poweroff
  exit 0
fi

# ---------------------------------------------------------------------------
# Check for active tmux sessions across all agent users
# ---------------------------------------------------------------------------
ACTIVE_SESSIONS=0
for i in 0 1 2 3; do
  agent_user="agent-${i}"
  if id "${agent_user}" &>/dev/null; then
    if su - "${agent_user}" -c "tmux has-session 2>/dev/null"; then
      ACTIVE_SESSIONS=$(( ACTIVE_SESSIONS + 1 ))
    fi
  fi
done

# ---------------------------------------------------------------------------
# Update last-active or check idle timeout
# ---------------------------------------------------------------------------
if [[ "${ACTIVE_SESSIONS}" -gt 0 ]]; then
  echo "${NOW}" > "${LAST_ACTIVE_FILE}"
  log "Active sessions: ${ACTIVE_SESSIONS} (wall-clock: ${WALL_CLOCK_HOURS}h, max: ${MAX_HOURS}h)"
  exit 0
fi

# No active sessions - check idle duration
if [[ -f "${LAST_ACTIVE_FILE}" ]]; then
  LAST_ACTIVE=$(cat "${LAST_ACTIVE_FILE}")
else
  # Never been active - use VM start as baseline
  LAST_ACTIVE="${VM_START}"
  echo "${LAST_ACTIVE}" > "${LAST_ACTIVE_FILE}"
fi

IDLE_SECS=$(( NOW - LAST_ACTIVE ))
IDLE_MINS=$(( IDLE_SECS / 60 ))
IDLE_THRESHOLD_SECS=$(( IDLE_MINUTES * 60 ))

log "No active sessions. Idle for ${IDLE_MINS}m (threshold: ${IDLE_MINUTES}m, wall-clock: ${WALL_CLOCK_HOURS}h)"

if [[ "${IDLE_SECS}" -ge "${IDLE_THRESHOLD_SECS}" ]]; then
  log "SHUTDOWN: idle threshold reached (${IDLE_MINS}m >= ${IDLE_MINUTES}m)"
  log "SHUTDOWN: initiating poweroff (reason: idle-timeout)"
  echo "idle-timeout" > "${SHUTDOWN_LOG}.reason"
  /sbin/poweroff
  exit 0
fi

log "Idle timer running: ${IDLE_MINS}m / ${IDLE_MINUTES}m until shutdown"
