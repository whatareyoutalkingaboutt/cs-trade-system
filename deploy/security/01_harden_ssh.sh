#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo SSH_PORT=52222 bash deploy/security/01_harden_ssh.sh

SSH_PORT="${SSH_PORT:-52222}"
SSHD_CONFIG="/etc/ssh/sshd_config"
BACKUP="/etc/ssh/sshd_config.bak.$(date +%Y%m%d%H%M%S)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

if [[ ! -f "${SSHD_CONFIG}" ]]; then
  echo "Missing ${SSHD_CONFIG}"
  exit 1
fi

cp "${SSHD_CONFIG}" "${BACKUP}"
echo "Backup created: ${BACKUP}"

set_or_append() {
  local key="$1"
  local value="$2"
  local file="$3"
  if grep -Eq "^[#[:space:]]*${key}[[:space:]]+" "${file}"; then
    sed -i.bak -E "s|^[#[:space:]]*${key}[[:space:]].*|${key} ${value}|g" "${file}"
  else
    printf "\n%s %s\n" "${key}" "${value}" >> "${file}"
  fi
}

set_or_append "Port" "${SSH_PORT}" "${SSHD_CONFIG}"
set_or_append "PasswordAuthentication" "no" "${SSHD_CONFIG}"
set_or_append "PubkeyAuthentication" "yes" "${SSHD_CONFIG}"
set_or_append "PermitRootLogin" "prohibit-password" "${SSHD_CONFIG}"
set_or_append "ChallengeResponseAuthentication" "no" "${SSHD_CONFIG}"
set_or_append "UsePAM" "yes" "${SSHD_CONFIG}"

if command -v sshd >/dev/null 2>&1; then
  sshd -t
fi

if systemctl list-unit-files | grep -q "^ssh.service"; then
  systemctl restart ssh
else
  systemctl restart sshd
fi

echo "SSH hardening applied."
echo "SSH port: ${SSH_PORT}"
echo "IMPORTANT: open firewall for ${SSH_PORT}/tcp before closing current session."
