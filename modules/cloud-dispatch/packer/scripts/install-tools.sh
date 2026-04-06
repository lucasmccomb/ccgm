#!/usr/bin/env bash
# install-tools.sh — Install the Claude Code agent toolchain.
# Called by Packer with NODE_VERSION and CLAUDE_CODE_VERSION env vars set.
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-22}"
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-1.2.3}"

echo "==> Installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  curl \
  git \
  jq \
  tmux \
  python3 \
  python3-pip \
  ca-certificates \
  gnupg \
  lsb-release \
  iptables-persistent \
  unattended-upgrades

echo "==> Installing Node.js ${NODE_VERSION} LTS (NodeSource)"
curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | bash -
apt-get install -y nodejs
node --version
npm --version

echo "==> Installing pnpm"
npm install -g pnpm
pnpm --version

echo "==> Installing Claude Code CLI v${CLAUDE_CODE_VERSION}"
npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

# Confirm the binary is on PATH
if command -v claude >/dev/null 2>&1; then
  echo "claude binary found: $(command -v claude)"
else
  echo "WARNING: claude binary not on PATH after install — continuing"
fi

echo "==> Installing Playwright with Chromium"
# Install at a system level so all agent users can invoke it
npm install -g playwright
npx playwright install --with-deps chromium

echo "==> Tool installation complete"
