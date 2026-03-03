#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo SSH_PORT=52222 bash deploy/security/02_configure_ufw.sh

SSH_PORT="${SSH_PORT:-52222}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

if ! command -v ufw >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ufw
fi

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

ufw allow "${SSH_PORT}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp

ufw --force enable
ufw status verbose

echo "UFW configured."
