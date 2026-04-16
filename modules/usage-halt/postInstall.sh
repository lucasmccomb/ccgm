#!/usr/bin/env bash
# postInstall.sh - Install and load the launchd agent that polls ccusage every 60s.
#
# Writes ~/Library/LaunchAgents/com.lem.claude-usage-monitor.plist and loads it.
# Installs ccusage globally if npm is available and ccusage is not already on PATH.
set -euo pipefail

PLIST_PATH="${HOME}/Library/LaunchAgents/com.lem.claude-usage-monitor.plist"
MONITOR_PATH="${HOME}/.claude/hooks/usage-monitor.sh"
LABEL="com.lem.claude-usage-monitor"
THRESHOLD="${HALT_THRESHOLD:-99}"

# ---- Install ccusage if missing ---------------------------------------------

if ! command -v ccusage &>/dev/null; then
  if command -v npm &>/dev/null; then
    echo "Installing ccusage globally..."
    npm i -g ccusage >/dev/null 2>&1 || echo "WARNING: ccusage install failed; monitor will fall back to npx at runtime"
  else
    echo "WARNING: npm not found; monitor will fall back to 'npx -y ccusage@latest' at runtime (slower)"
  fi
fi

# ---- Ensure monitor script exists -------------------------------------------

if [[ ! -f "${MONITOR_PATH}" ]]; then
  echo "ERROR: ${MONITOR_PATH} not found. The usage-halt module files may not have linked correctly." >&2
  exit 1
fi

# ---- Build PATH for launchd env --------------------------------------------

# launchd runs with a minimal PATH; we need node (for ccusage) and jq.
NODE_BIN=""
if command -v node &>/dev/null; then
  NODE_BIN="$(dirname "$(command -v node)")"
fi

LAUNCHD_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
if [[ -n "${NODE_BIN}" ]]; then
  LAUNCHD_PATH="${NODE_BIN}:${LAUNCHD_PATH}"
fi

# ---- Write plist ------------------------------------------------------------

mkdir -p "$(dirname "${PLIST_PATH}")"

cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${MONITOR_PATH}</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/.claude/halt-monitor.out.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/.claude/halt-monitor.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${LAUNCHD_PATH}</string>
        <key>HALT_THRESHOLD</key>
        <string>${THRESHOLD}</string>
    </dict>
</dict>
</plist>
EOF

echo "Wrote ${PLIST_PATH}"

# ---- Load (or reload) launchd agent -----------------------------------------

# Unload first if already loaded (idempotent reinstall)
launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl load -w "${PLIST_PATH}"

if launchctl list | grep -q "${LABEL}"; then
  echo "Loaded launchd agent ${LABEL} (polls every 60s)"
else
  echo "WARNING: launchd agent did not appear in launchctl list" >&2
fi

echo ""
echo "To disable: launchctl unload ${PLIST_PATH}"
echo "To override a live halt: rm ${HOME}/.claude/halt.flag"
echo "Logs: ${HOME}/.claude/halt.log"
