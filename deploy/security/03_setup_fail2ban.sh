#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo SSH_PORT=52222 bash deploy/security/03_setup_fail2ban.sh

SSH_PORT="${SSH_PORT:-52222}"
JAIL_FILE="/etc/fail2ban/jail.d/sshd.local"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

apt-get update
apt-get install -y fail2ban

mkdir -p /etc/fail2ban/jail.d
cat > "${JAIL_FILE}" <<EOF
[sshd]
enabled = true
port = ${SSH_PORT}
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF

systemctl enable fail2ban
systemctl restart fail2ban
sleep 1
fail2ban-client status sshd || true

echo "Fail2Ban configured."
