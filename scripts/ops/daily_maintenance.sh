#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/cs-item-scraper}"
LOG_DIR="${PROJECT_DIR}/reports/maintenance"
RUN_DATE="$(date +%Y%m%d)"
RUN_AT="$(date '+%Y-%m-%d %H:%M:%S%z')"
LOG_FILE="${LOG_DIR}/daily_maintenance_${RUN_DATE}.log"

mkdir -p "${LOG_DIR}"
exec >>"${LOG_FILE}" 2>&1

echo "==== [${RUN_AT}] daily maintenance start ===="
echo "[host] $(hostname)"
echo "[uptime] $(uptime -p || true)"

cd "${PROJECT_DIR}"

echo "[disk]"
df -h / /opt || true

echo "[memory]"
free -h || true

echo "[docker compose ps]"
docker compose ps || true

echo "[health]"
timeout 15 curl -fsS http://127.0.0.1:8000/health || echo "health_check_failed"

echo "[warm rankings cache]"
timeout 120 docker compose exec -T api python -c "from backend.scrapers.celery_tasks import calculate_daily_rankings; print(calculate_daily_rankings())" || echo "rankings_warm_failed"

echo "[rankings latency]"
/usr/bin/time -f 'rankings_latency=%E' timeout 20 curl -fsS -o /dev/null "http://127.0.0.1:8000/api/items/rankings?source=auto" || echo "rankings_latency_failed"

echo "[docker stats]"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' || true

echo "[recent oom events (24h)]"
timeout 8 docker events --since 24h --until 0s --filter event=oom || true

echo "==== [$(date '+%Y-%m-%d %H:%M:%S%z')] daily maintenance end ===="
