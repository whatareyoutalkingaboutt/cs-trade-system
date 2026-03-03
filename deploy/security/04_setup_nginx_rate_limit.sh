#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo DOMAIN=example.com bash deploy/security/04_setup_nginx_rate_limit.sh

DOMAIN="${DOMAIN:-_}"
CONF_SRC="$(cd "$(dirname "$0")/.." && pwd)/nginx/cs-item-scraper.conf"
CONF_DST="/etc/nginx/sites-available/cs-item-scraper.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

apt-get update
apt-get install -y nginx

if [[ ! -f "${CONF_SRC}" ]]; then
  echo "Missing nginx template: ${CONF_SRC}"
  exit 1
fi

sed "s/__SERVER_NAME__/${DOMAIN}/g" "${CONF_SRC}" > "${CONF_DST}"
ln -sf "${CONF_DST}" /etc/nginx/sites-enabled/cs-item-scraper.conf
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl enable nginx
systemctl restart nginx

echo "Nginx rate-limit config applied."
