#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/cs-item-scraper}"
LOG_DIR="${PROJECT_DIR}/reports/maintenance"
ENV_FILE="${PROJECT_DIR}/.env"
RUN_DATE="$(date +%Y%m%d)"
RUN_AT="$(date '+%Y-%m-%d %H:%M:%S%z')"
LOG_FILE="${LOG_DIR}/daily_maintenance_${RUN_DATE}.log"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

to_bool() {
  local raw
  raw="$(printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "${raw}" == "1" || "${raw}" == "true" || "${raw}" == "yes" || "${raw}" == "on" ]]
}

MAINTENANCE_EMAIL_ENABLED="${MAINTENANCE_EMAIL_ENABLED:-false}"
MAINTENANCE_EMAIL_ONLY_ON_FAILURE="${MAINTENANCE_EMAIL_ONLY_ON_FAILURE:-false}"
MAINTENANCE_EMAIL_SUBJECT_PREFIX="${MAINTENANCE_EMAIL_SUBJECT_PREFIX:-[维护日报]}"

mkdir -p "${LOG_DIR}"
exec >>"${LOG_FILE}" 2>&1

echo "==== [${RUN_AT}] daily maintenance start ===="
echo "[host] $(hostname)"
echo "[uptime] $(uptime -p || true)"

cd "${PROJECT_DIR}"

failure_count=0
health_status="ok"
rankings_warm_status="ok"
rankings_latency_status="ok"

echo "[disk]"
df -h / /opt || true

echo "[memory]"
free -h || true

echo "[docker compose ps]"
docker compose ps || true

echo "[health]"
if ! timeout 15 curl -fsS http://127.0.0.1:8000/health; then
  health_status="failed"
  failure_count=$((failure_count + 1))
  echo "health_check_failed"
fi

echo "[warm rankings cache]"
if ! timeout 120 docker compose exec -T api python -c "from backend.scrapers.celery_tasks import calculate_daily_rankings; print(calculate_daily_rankings())"; then
  rankings_warm_status="failed"
  failure_count=$((failure_count + 1))
  echo "rankings_warm_failed"
fi

echo "[rankings latency]"
if ! /usr/bin/time -f 'rankings_latency=%E' timeout 20 curl -fsS -o /dev/null "http://127.0.0.1:8000/api/items/rankings?source=auto"; then
  rankings_latency_status="failed"
  failure_count=$((failure_count + 1))
  echo "rankings_latency_failed"
fi

echo "[docker stats]"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' || true

echo "[recent oom events (24h)]"
oom_events="$(timeout 8 docker events --since 24h --until 0s --filter event=oom 2>/dev/null || true)"
if [[ -n "${oom_events}" ]]; then
  printf "%s\n" "${oom_events}"
fi
oom_count="$(printf "%s\n" "${oom_events}" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"

overall_status="ok"
if (( failure_count > 0 )); then
  overall_status="degraded"
fi
if [[ "${oom_count}" != "0" ]]; then
  overall_status="warning"
fi

echo "[summary] overall=${overall_status} failures=${failure_count} health=${health_status} rankings_warm=${rankings_warm_status} rankings_latency=${rankings_latency_status} oom_24h=${oom_count}"

if to_bool "${MAINTENANCE_EMAIL_ENABLED}" && { ! to_bool "${MAINTENANCE_EMAIL_ONLY_ON_FAILURE}" || (( failure_count > 0 )) || [[ "${oom_count}" != "0" ]]; }; then
  email_subject="${MAINTENANCE_EMAIL_SUBJECT_PREFIX} $(hostname) ${RUN_DATE} ${overall_status}"
  email_html="<h3>每日维护结果</h3><p>主机：$(hostname)</p><p>时间：${RUN_AT}</p><p>状态：${overall_status}</p><p>失败数：${failure_count}</p><p>健康检查：${health_status}</p><p>榜单预热：${rankings_warm_status}</p><p>榜单延迟探测：${rankings_latency_status}</p><p>24小时OOM：${oom_count}</p><p>日志：${LOG_FILE}</p>"
  if timeout 30 docker compose exec -T \
    -e MAINT_SUBJECT="${email_subject}" \
    -e MAINT_HTML="${email_html}" \
    api python -c "import os; from backend.services.email_service import send_qq_email; print('maintenance_email_sent=' + ('1' if send_qq_email(os.getenv('MAINT_SUBJECT', ''), os.getenv('MAINT_HTML', '')) else '0'))"; then
    echo "[mail] maintenance summary sent"
  else
    echo "[mail] maintenance summary send failed"
  fi
else
  echo "[mail] skipped"
fi

echo "==== [$(date '+%Y-%m-%d %H:%M:%S%z')] daily maintenance end ===="
