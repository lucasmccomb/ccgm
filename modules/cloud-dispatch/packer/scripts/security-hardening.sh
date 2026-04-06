#!/usr/bin/env bash
# security-hardening.sh — iptables egress rules, SSH hardening, auto-updates.
# Runs as root inside the Packer builder VM.
set -euo pipefail

echo "==> Resolving allowed destination IPs for iptables rules"

# Resolve hostnames at image-build time and embed them.
# At runtime the VM will use these rules; the orchestrator can also regenerate
# them on first boot if IP addresses change.
resolve_ips() {
  host "$1" 2>/dev/null \
    | grep "has address" \
    | awk '{print $NF}' \
    | sort -u
}

GITHUB_IPS=$(resolve_ips github.com || true)
ANTHROPIC_IPS=$(resolve_ips api.anthropic.com || true)
NPMJS_IPS=$(resolve_ips registry.npmjs.org || true)

echo "  github.com:            ${GITHUB_IPS:-<unresolved>}"
echo "  api.anthropic.com:     ${ANTHROPIC_IPS:-<unresolved>}"
echo "  registry.npmjs.org:    ${NPMJS_IPS:-<unresolved>}"

echo "==> Installing iptables-persistent"
export DEBIAN_FRONTEND=noninteractive
# Pre-answer debconf prompts so iptables-persistent install is non-interactive
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean false | debconf-set-selections
apt-get install -y iptables-persistent

echo "==> Configuring OUTPUT chain"
# Flush existing OUTPUT rules, then rebuild
iptables -F OUTPUT

# ALLOW: loopback
iptables -A OUTPUT -o lo -j ACCEPT

# ALLOW: established / related connections (replies to inbound SSH, etc.)
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# ALLOW: DNS (UDP 53)
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# ALLOW: NTP (UDP 123)
iptables -A OUTPUT -p udp --dport 123 -j ACCEPT

# ALLOW: HTTPS (TCP 443) to known allowlisted hosts
add_https_allow() {
  local ip="$1"
  iptables -A OUTPUT -p tcp --dport 443 -d "${ip}" -j ACCEPT
}

add_ssh_allow() {
  local ip="$1"
  iptables -A OUTPUT -p tcp --dport 22 -d "${ip}" -j ACCEPT
}

for ip in ${GITHUB_IPS}; do
  add_https_allow "${ip}"
  add_ssh_allow "${ip}"   # git+ssh to GitHub
done

for ip in ${ANTHROPIC_IPS}; do
  add_https_allow "${ip}"
done

for ip in ${NPMJS_IPS}; do
  add_https_allow "${ip}"
done

# BLOCK: EC2/Hetzner metadata API from non-root processes
# (root needs it for SSH key injection via cloud-init)
iptables -A OUTPUT \
  -m owner ! --uid-owner 0 \
  -d 169.254.169.254 \
  -j DROP

# DROP all other outbound traffic from agent users (uid 1000+)
iptables -A OUTPUT \
  -m owner --uid-owner 1000:65534 \
  -j DROP

# Root retains full outbound access so the orchestrator SSH session works.
iptables -A OUTPUT -m owner --uid-owner 0 -j ACCEPT

echo "==> Saving iptables rules for persistence across reboots"
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

echo "==> Hardening sshd_config"
SSHD_CONF="/etc/ssh/sshd_config"

# Disable password authentication — key-only access
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "${SSHD_CONF}"
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "${SSHD_CONF}"
sed -i 's/^#\?UsePAM.*/UsePAM no/' "${SSHD_CONF}"

# Ensure PermitRootLogin is set (orchestrator needs root SSH)
if grep -q '^PermitRootLogin' "${SSHD_CONF}"; then
  sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' "${SSHD_CONF}"
else
  echo "PermitRootLogin prohibit-password" >> "${SSHD_CONF}"
fi

# Reload sshd if it is running (it won't be during Packer build, but be safe)
systemctl is-active sshd && systemctl reload sshd || true

echo "==> Configuring unattended security updates"
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'APT_CONF'
Unattended-Upgrade::Allowed-Origins {
  "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::Package-Blacklist {};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
APT_CONF

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT_CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT_CONF

echo "==> security-hardening.sh complete"
