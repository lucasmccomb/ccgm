#!/usr/bin/env bash
# setup.sh — Create agent users, shared directories, and git/SSH baseline config.
set -euo pipefail

AGENT_COUNT=4
CCGM_DIR="/opt/ccgm"
SECRETS_BASE="/run/secrets"

echo "==> Creating /opt/ccgm shared directory"
mkdir -p "${CCGM_DIR}"
chmod 755 "${CCGM_DIR}"

echo "==> Creating agent user accounts (agent-0 through agent-$((AGENT_COUNT - 1)))"
for i in $(seq 0 $((AGENT_COUNT - 1))); do
  USER="agent-${i}"

  if id "${USER}" &>/dev/null; then
    echo "  ${USER} already exists, skipping"
  else
    useradd \
      --create-home \
      --shell /bin/bash \
      --comment "CCGM agent ${i}" \
      "${USER}"
    echo "  created ${USER}"
  fi

  HOME_DIR="/home/${USER}"

  # Restrict home directory to owner only
  chmod 700 "${HOME_DIR}"

  # Disable shell history — agents should not accumulate history on disk
  cat >> "${HOME_DIR}/.bashrc" <<'BASHRC'

# CCGM agent config — do not modify
export HISTFILE=/dev/null
export HISTSIZE=0
BASHRC

  chown "${USER}:${USER}" "${HOME_DIR}/.bashrc"

  # Global git identity (placeholder; real creds are injected at runtime)
  git_config="${HOME_DIR}/.gitconfig"
  cat > "${git_config}" <<GITCONFIG
[user]
  name = agent-${i}
  email = agent-${i}@localhost
[credential]
  helper = store
[init]
  defaultBranch = main
GITCONFIG
  chown "${USER}:${USER}" "${git_config}"

  # SSH config — trust GitHub host key on first connect
  ssh_dir="${HOME_DIR}/.ssh"
  mkdir -p "${ssh_dir}"
  chmod 700 "${ssh_dir}"
  cat > "${ssh_dir}/config" <<'SSHCONFIG'
Host github.com
  HostName github.com
  User git
  StrictHostKeyChecking accept-new
  IdentityFile ~/.ssh/id_ed25519
SSHCONFIG
  chmod 600 "${ssh_dir}/config"
  chown -R "${USER}:${USER}" "${ssh_dir}"
done

echo "==> Creating /run/secrets mount points for agent credential injection"
# /run is tmpfs on boot; we just need the parent directories to exist in the
# image so cloud-init / the orchestrator can mount tmpfs over them at runtime.
mkdir -p "${SECRETS_BASE}"
for i in $(seq 0 $((AGENT_COUNT - 1))); do
  mkdir -p "${SECRETS_BASE}/agent-${i}"
  chmod 700 "${SECRETS_BASE}/agent-${i}"
done

echo "==> Removing agent users from sudo"
# Users created without --groups sudo/wheel by default, but double-check
for i in $(seq 0 $((AGENT_COUNT - 1))); do
  USER="agent-${i}"
  if groups "${USER}" | grep -qE '(sudo|wheel)'; then
    deluser "${USER}" sudo 2>/dev/null || gpasswd -d "${USER}" sudo 2>/dev/null || true
    echo "  removed ${USER} from sudo"
  fi
done

echo "==> setup.sh complete"
