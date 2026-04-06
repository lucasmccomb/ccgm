#!/usr/bin/env bash
# validate.sh — Verify the golden image has everything it needs.
# Runs as root inside the Packer builder VM after all other provisioners.
set -euo pipefail

FAILURES=0

check() {
  local label="$1"
  shift
  if "$@" &>/dev/null; then
    echo "  [PASS] ${label}"
  else
    echo "  [FAIL] ${label}"
    FAILURES=$((FAILURES + 1))
  fi
}

check_file() {
  local label="$1"
  local path="$2"
  check "${label}" test -e "${path}"
}

check_user() {
  local user="$1"
  check "user ${user} exists" id "${user}"
  check "user ${user} home chmod 700" test "$(stat -c '%a' "/home/${user}")" = "700"
  check "user ${user} not in sudo" bash -c "! groups ${user} | grep -qE '(sudo|wheel)'"
  check "user ${user} HISTFILE=/dev/null" grep -q "HISTFILE=/dev/null" "/home/${user}/.bashrc"
  check "user ${user} .ssh config exists" test -f "/home/${user}/.ssh/config"
}

echo "==> Verifying installed tools"
check "node installed"       node --version
check "npm installed"        npm --version
check "pnpm installed"       pnpm --version
check "git installed"        git --version
check "tmux installed"       tmux -V
check "jq installed"         jq --version
check "curl installed"       curl --version
check "python3 installed"    python3 --version
check "playwright installed" npx playwright --version

# claude binary may be at a non-standard path; check both
if command -v claude &>/dev/null; then
  echo "  [PASS] claude binary on PATH"
else
  claude_path=$(find /usr/local/lib /usr/lib -name "claude" -type f 2>/dev/null | head -1)
  if [ -n "${claude_path}" ]; then
    echo "  [PASS] claude binary found at ${claude_path}"
  else
    echo "  [FAIL] claude binary not found"
    FAILURES=$((FAILURES + 1))
  fi
fi

echo "==> Verifying agent users"
for i in 0 1 2 3; do
  check_user "agent-${i}"
done

echo "==> Verifying /opt/ccgm directory"
check_file "/opt/ccgm exists" "/opt/ccgm"

echo "==> Verifying iptables rules are active"
check "iptables OUTPUT rules present" bash -c "iptables -L OUTPUT -n | grep -q 'DROP\|ACCEPT'"
check "iptables rules persisted to disk" test -f "/etc/iptables/rules.v4"
check "metadata API rule present" bash -c "iptables -L OUTPUT -n | grep -q '169.254.169.254'"

echo "==> Verifying SSH hardening"
check "sshd PasswordAuthentication off" grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config

echo "==> Verification summary"
if [ "${FAILURES}" -eq 0 ]; then
  echo "All checks passed. Image is ready."
else
  echo "${FAILURES} check(s) failed. Review the output above before distributing this snapshot."
  exit 1
fi
