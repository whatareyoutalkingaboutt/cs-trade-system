#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${1:-/opt/cs-item-scraper}"
SCRIPT_PATH="${PROJECT_DIR}/scripts/ops/daily_maintenance.sh"
CRON_EXPR="${CRON_EXPR:-10 8 * * *}"
BLOCK_START="# BEGIN cs-item-scraper daily-maintenance"
BLOCK_END="# END cs-item-scraper daily-maintenance"

if [[ ! -x "${SCRIPT_PATH}" ]]; then
  echo "script not executable: ${SCRIPT_PATH}" >&2
  exit 1
fi

TMP_FILE="$(mktemp)"
CURRENT_CRON="$(crontab -l 2>/dev/null || true)"

printf "%s\n" "${CURRENT_CRON}" | awk -v s="${BLOCK_START}" -v e="${BLOCK_END}" '
BEGIN { skip=0 }
$0==s { skip=1; next }
$0==e { skip=0; next }
skip==0 { print }
' > "${TMP_FILE}"

{
  cat "${TMP_FILE}"
  echo "${BLOCK_START}"
  echo "CRON_TZ=Asia/Shanghai"
  echo "${CRON_EXPR} ${SCRIPT_PATH}"
  echo "${BLOCK_END}"
} | sed '/^[[:space:]]*$/d' | crontab -

rm -f "${TMP_FILE}"

echo "installed cron:"
crontab -l | sed -n "/${BLOCK_START}/,/${BLOCK_END}/p"
