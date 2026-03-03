# CS-Item-Scraper 上线总清单（Ubuntu-24.04.1-x64）

适用流程：`本地代码 -> Gitee(主) + GitHub(备) -> 服务器从 Gitee 拉代码部署 -> (可选)数据库迁移`

## 0. 关键说明
- 不会直接把本地 Docker 容器/镜像/volume 搬到服务器。
- 服务器会用拉到的代码重新 `docker compose build/up`。
- 如需历史数据，需要单独迁移数据库（推荐只迁移 PostgreSQL）。
- 代码源策略：
  - 主源：`https://gitee.com/glzhxz/cs-trade-system.git`
  - 备用：`https://github.com/whatareyoutalkingaboutt/cs-trade-system.git`

---

## 1. 本地：提交并同步到 Gitee + GitHub

```bash
cd /Users/gaolaozhuanghouxianzi/cs-item-scraper
git status
git checkout -b release/ubuntu2404-deploy
git add .
git commit -m "deploy: ubuntu 24.04 production rollout"
git push -u origin release/ubuntu2404-deploy
git push -u gitee release/ubuntu2404-deploy
```

如需合并到主分支：
```bash
git checkout main
git merge --no-ff release/ubuntu2404-deploy
git push origin main
git push gitee main
```

如需覆盖旧版本（强制推送）：
```bash
git push origin main --force
git push gitee main --force
```

---

## 2. 服务器：首次部署（Ubuntu-24.04.1-x64）

### 2.1 安装依赖
```bash
sudo apt update
sudo apt -y install ca-certificates curl gnupg git nginx ufw
```

### 2.2 安装 Docker + Compose Plugin
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### 2.3 防火墙
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

### 2.4 拉代码
```bash
sudo mkdir -p /opt && sudo chown "$USER":"$USER" /opt
cd /opt
git clone https://gitee.com/glzhxz/cs-trade-system.git cs-item-scraper
cd cs-item-scraper
```

### 2.5 配置 `.env`
```bash
cp .env.example .env
```

至少修改：
- `DB_PASSWORD`
- `DRAGONFLY_PASSWORD`
- `SECRET_KEY`（建议 `openssl rand -hex 32`）
- `DEFAULT_ADMIN_BOOTSTRAP_KEY`（建议 `openssl rand -hex 32`）
- `ADMIN_LOGIN_KEY`（建议 `openssl rand -hex 24`）
- `CORS_ORIGINS=https://<你的域名>`
- `CELERY_WORKER_CONCURRENCY=1`（2核2G 建议先 1）
- `NEXT_PUBLIC_API_URL=`（留空）
- `NEXT_PUBLIC_WS_URL=`（留空）

### 2.6 启动服务
```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=120 api ws-server frontend celery-worker celery-beat
```

### 2.7 配置 Nginx
```bash
sudo cp deploy/nginx/cs-item-scraper.conf /etc/nginx/sites-available/cs-item-scraper.conf
sudo sed -i "s/__SERVER_NAME__/<你的域名>/g" /etc/nginx/sites-available/cs-item-scraper.conf
sudo ln -sf /etc/nginx/sites-available/cs-item-scraper.conf /etc/nginx/sites-enabled/cs-item-scraper.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 2.8 HTTPS 证书
```bash
sudo apt -y install certbot python3-certbot-nginx
sudo certbot --nginx -d <你的域名> --redirect -m <你的邮箱> --agree-tos -n
sudo systemctl status certbot.timer --no-pager
```

---

## 3. 可选：从本地迁移 PostgreSQL 数据

### 3.1 本地导出
```bash
cd /Users/gaolaozhuanghouxianzi/cs-item-scraper
TS=$(date +%Y%m%d_%H%M%S)
ART_DIR="migration_artifacts/$TS"
mkdir -p "$ART_DIR"
docker compose exec -T timescaledb pg_dump -U postgres -d cs_items -Fc > "$ART_DIR/cs_items.dump"
docker compose exec -T timescaledb pg_dumpall -U postgres --globals-only > "$ART_DIR/globals.sql"
```

### 3.2 上传到服务器
```bash
scp -r "$ART_DIR" <server_user>@<server_ip>:/opt/cs-item-scraper/migration_artifacts/
```

### 3.3 服务器导入
```bash
cd /opt/cs-item-scraper
IMPORT_DIR="migration_artifacts/<你的时间戳目录>"
docker compose stop api ws-server celery-worker celery-beat frontend
if [ -f "$IMPORT_DIR/globals.sql" ]; then
  cat "$IMPORT_DIR/globals.sql" | docker compose exec -T timescaledb psql -U postgres
fi
docker compose exec -T timescaledb dropdb -U postgres --if-exists cs_items
docker compose exec -T timescaledb createdb -U postgres cs_items
cat "$IMPORT_DIR/cs_items.dump" | docker compose exec -T timescaledb pg_restore -U postgres -d cs_items --clean --if-exists --no-owner --no-privileges
docker compose up -d
docker compose ps
```

---

## 4. 上线验收

```bash
curl -s http://127.0.0.1:8000/health
curl -I https://<你的域名>
docker compose ps
docker compose logs --tail=120 api ws-server frontend celery-worker celery-beat
docker compose exec -T timescaledb psql -U postgres -d cs_items -c "SELECT NOW();"
```

预期：
- `health` 返回 `{"status":"ok"}`
- 域名访问正常（200/301）
- 关键服务 `Up`

---

## 5. 后续每次发布

```bash
cd /opt/cs-item-scraper
git fetch --all
git checkout main
git pull
docker compose up -d --build
docker compose logs --tail=100 api ws-server frontend celery-worker celery-beat
```

如 Gitee 临时不可用，切换到 GitHub：
```bash
cd /opt/cs-item-scraper
git remote set-url origin https://github.com/whatareyoutalkingaboutt/cs-trade-system.git
git fetch --all
git checkout main
git pull
docker compose up -d --build
```
