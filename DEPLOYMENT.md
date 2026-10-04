# Nifty 100 Financial Intelligence Platform — Deployment Guide

This document walks you through deploying the platform in four environments,
from "run it on my laptop" to a production Linux VM with Nginx reverse proxy
and systemd services. Pick the section that matches your use case.

---

## 0. Prerequisites (all environments)

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python      | 3.12    | 3.13       |
| pip         | 23.x    | latest     |
| RAM         | 2 GB    | 4 GB       |
| Disk        | 1 GB free (DB + reports) | 2 GB |
| OS          | Linux / macOS / WSL2 | Ubuntu 22.04 LTS |
| Git         | any recent | 2.40+ |

Optional (for production):
- Docker 24+ & Docker Compose v2
- Nginx (if terminating TLS / proxying)
- A non-root `nifty` user on the target host

---

## 1. Option A — Local Dev Quickstart (5 minutes)

Fastest path to get the dashboard and API running on your machine using the
pre-built SQLite DB that ships with the repo (92 companies already loaded).

```bash
# 1. Clone
git clone https://github.com/mattperrymatt45-pixel/nifty100.git
cd nifty100

# 2. Create virtual environment
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install
pip install --upgrade pip
make install                       # or: pip install -r requirements.txt

# 4. (Optional) dev tooling — Black, Ruff, pytest, pre-commit
make install-dev

# 5. Configure
cp .env.example .env               # edit values if needed (defaults work)

# 6. Verify the shipped DB works
python -c "import sqlite3; c=sqlite3.connect('db/nifty100.db'); \
           print('companies:', c.execute('select count(*) from companies').fetchone()[0])"
# -> companies: 92

# 7. Run the test suite (sanity check)
pytest tests/ -q --no-cov         # expect ~695 passed, 0 failed

# 8. Launch services (in two separate terminals)
make run-api                       # FastAPI on http://localhost:8000
make run-dashboard                 # Streamlit on http://localhost:8501
```

After launch:
- **API**: http://localhost:8000/docs (Swagger UI), http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/api/v1/openapi.json
- **Dashboard**: http://localhost:8501
- **Health**: http://localhost:8000/api/v1/health

### Regenerate everything from raw data (optional)
If you want to rebuild `db/nifty100.db` from the Excel files in `data/raw/`
instead of using the shipped DB:

```bash
make load-reset                    # truncates + reloads all tables
make populate-ratios               # computes & fills financial_ratios
make capital-alloc                 # writes output/capital_allocation.csv
make screener-export-all           # writes output/screener_output.xlsx
make report                        # generates tearsheets, sector & portfolio PDFs
```

---

## 2. Option B — Fresh Build on a Linux Server (Ubuntu 22.04)

Step-by-step for a cloud VM (AWS EC2, GCP Compute, DigitalOcean Droplet, etc.).

### 2.1 System prep
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.13 python3.13-venv python3-pip git build-essential \
                    libsqlite3-dev nginx
# If python3.13 is not in default apt, use the deadsnakes PPA:
# sudo add-apt-repository ppa:deadsnakes/ppa -y && sudo apt update
```

### 2.2 Create a service user
```bash
sudo useradd -r -m -s /bin/bash nifty
sudo mkdir -p /opt/nifty100 /var/log/nifty100
sudo chown nifty:nifty /opt/nifty100 /var/log/nifty100
sudo -u nifty -i
```

### 2.3 Clone & install
```bash
cd /opt/nifty100
git clone https://github.com/mattperrymatt45-pixel/nifty100.git .
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to use absolute paths:
```ini
DB_PATH=/opt/nifty100/db/nifty100.db
DB_CONNECTION_STRING=sqlite:////opt/nifty100/db/nifty100.db
LOG_FILE=/var/log/nifty100/nifty100.log
API_HOST=0.0.0.0
API_PORT=8000
DASHBOARD_PORT=8501
```

### 2.4 Verify
```bash
source /opt/nifty100/.venv/bin/activate
cd /opt/nifty100
pytest tests/ -q --no-cov
```

### 2.5 systemd services

Create `/etc/systemd/system/nifty-api.service`:
```ini
[Unit]
Description=Nifty 100 FastAPI
After=network.target

[Service]
User=nifty
Group=nifty
WorkingDirectory=/opt/nifty100
Environment="PATH=/opt/nifty100/.venv/bin"
ExecStart=/opt/nifty100/.venv/bin/uvicorn src.api.main:app \
    --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:/var/log/nifty100/api.log
StandardError=append:/var/log/nifty100/api.err.log

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/nifty-dashboard.service`:
```ini
[Unit]
Description=Nifty 100 Streamlit Dashboard
After=network.target

[Service]
User=nifty
Group=nifty
WorkingDirectory=/opt/nifty100
Environment="PATH=/opt/nifty100/.venv/bin"
ExecStart=/opt/nifty100/.venv/bin/streamlit run src/dashboard/app.py \
    --server.port 8501 --server.address 127.0.0.1 \
    --server.headless true --browser.gatherUsageStats false
Restart=always
RestartSec=5
StandardOutput=append:/var/log/nifty100/dashboard.log
StandardError=append:/var/log/nifty100/dashboard.err.log

[Install]
WantedBy=multi-user.target
```

Enable & start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nifty-api nifty-dashboard
sudo systemctl status nifty-api nifty-dashboard
```

### 2.6 Nginx reverse proxy (TLS-ready)

Create `/etc/nginx/sites-available/nifty100`:
```nginx
server {
    listen 80;
    server_name nifty.yourdomain.com;

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Swagger / OpenAPI
    location /docs { proxy_pass http://127.0.0.1:8000/docs; }
    location /redoc { proxy_pass http://127.0.0.1:8000/redoc; }
    location /openapi.json { proxy_pass http://127.0.0.1:8000/openapi.json; }

    # Streamlit dashboard
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/nifty100 /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For HTTPS, install Certbot:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d nifty.yourdomain.com
```

### 2.7 Firewall
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

The API is now at `https://nifty.yourdomain.com/api/v1/health` and the
dashboard at `https://nifty.yourdomain.com/`.

---

## 3. Option C — Docker Deployment

### 3.1 Dockerfile

Create `Dockerfile` in the project root:
```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for SQLite/ReportLab image work
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libsqlite3-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Default to the API; override with `docker run ... dashboard`
EXPOSE 8000 8501

COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["api"]
```

Create `docker-entrypoint.sh`:
```bash
#!/bin/bash
set -e
case "$1" in
    api)
        exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 2
        ;;
    dashboard)
        exec streamlit run src/dashboard/app.py \
             --server.port 8501 --server.address 0.0.0.0 \
             --server.headless true --browser.gatherUsageStats false
        ;;
    etl)
        python -m scripts.run_etl --reset
        python -m scripts.populate_ratios --reset
        python -m scripts.export_screener
        ;;
    *)
        exec "$@"
        ;;
esac
```

### 3.2 docker-compose.yml
```yaml
version: "3.9"

services:
  api:
    build: .
    command: api
    ports:
      - "8000:8000"
    volumes:
      - ./db:/app/db
      - ./output:/app/output
      - ./logs:/app/logs
    environment:
      - DB_CONNECTION_STRING=sqlite:////app/db/nifty100.db
      - LOG_LEVEL=INFO
    restart: unless-stopped

  dashboard:
    build: .
    command: dashboard
    ports:
      - "8501:8501"
    volumes:
      - ./db:/app/db
      - ./output:/app/output
      - ./reports:/app/reports
    environment:
      - API_BASE_URL=http://api:8000/api/v1
    depends_on:
      - api
    restart: unless-stopped
```

### 3.3 Build & run
```bash
# If ETL hasn't run yet (no db/nifty100.db), build the DB first:
docker compose run --rm etl

# Start services
docker compose up -d --build

# Logs
docker compose logs -f api
docker compose logs -f dashboard
```

- API: http://localhost:8000/api/v1/health
- Dashboard: http://localhost:8501
- Swagger: http://localhost:8000/docs

---

## 4. Option D — Production Hardening Checklist

Once either B or C is up, go through this list before going live:

- [ ] **Auth**: The API ships with CORS `allow_origins=["*"]` and no auth.
      Add an API key header dependency or OAuth2 if exposing publicly.
      Patch `src/api/main.py` CORSMiddleware to list only allowed origins.
- [ ] **TLS**: Terminate HTTPS at Nginx / your load balancer; HSTS header.
- [ ] **Rate limiting**: Add `slowapi` (or Nginx `limit_req`) to `/api/v1/`.
- [ ] **Logging**: Send `/var/log/nifty100/*.log` to a central aggregator
      (ELK, Loki, CloudWatch). Logrotate is already configured via Loguru
      `LOG_ROTATION=10 MB` + `LOG_RETENTION=30 days`.
- [ ] **Backups**: Schedule daily backup of `db/nifty100.db` (SQLite backup
      API — do **not** just cp while the DB is being written to):
      ```bash
      sqlite3 /opt/nifty100/db/nifty100.db ".backup '/var/backups/nifty100-$(date +%F).db'"
      ```
- [ ] **Scheduled refreshes**: If you wire a live data feed, add a cron job:
      ```cron
      0 2 * * 1  cd /opt/nifty100 && /opt/nifty100/.venv/bin/python -m scripts.run_etl >> /var/log/nifty100/etl.log 2>&1
      ```
- [ ] **Health check**: Confirm uptime externally (UptimeRobot, Pingdom):
      `GET https://nifty.yourdomain.com/api/v1/health` returns HTTP 200
      with `"status":"ok"`.
- [ ] **Monitoring**: Track process memory/CPU with Prometheus node_exporter
      or Datadog. FastAPI exposes a natural hook for `/metrics` if you add
      `prometheus-fastapi-instrumentator`.
- [ ] **Secrets**: Move `.env` ownership to `root:nifty`, mode `0640`, never
      commit it (`.env` is in `.gitignore`).
- [ ] **Workers**: The example uses 2 Uvicorn workers. For a heavier box
      (4 vCPU / 8 GB), bump to `--workers 4`. SQLite supports multiple
      readers well; writes are serialized, which is fine for this workload.
- [ ] **DB upgrade path**: To move from SQLite to Postgres, change
      `DB_CONNECTION_STRING` in `.env` to `postgresql+psycopg://user:pwd@host/db`
      and `pip install psycopg[binary]`. The schema is SQLAlchemy-mapped,
      so the DDL is portable; rerun `make load-reset` to populate.

---

## 5. Verifying a Deployment

After the services are up, run these smoke tests:

```bash
# 1. Health endpoint
curl -s http://localhost:8000/api/v1/health | python -m json.tool
# expect: {"status":"ok", ..., "version":"1.0.0-sprint6"}

# 2. Companies list returns 92
curl -s http://localhost:8000/api/v1/companies/ | python -c "import sys,json; print('count:', json.load(sys.stdin)['count'])"
# expect: count: 92

# 3. TCS detail endpoint
curl -s http://localhost:8000/api/v1/companies/TCS | python -c "import sys,json; d=json.load(sys.stdin); print(d['company_name'], '|', d['broad_sector'])"
# expect: Tata Consultancy Services | Information Technology

# 4. Screener presets
curl -s "http://localhost:8000/api/v1/screener/?preset=quality_compounder" | python -c "import sys,json; print('QC hits:', json.load(sys.stdin)['count'])"

# 5. Sectors
curl -s http://localhost:8000/api/v1/sectors/ | python -c "import sys,json; print('sectors:', json.load(sys.stdin)['count'])"
# expect: sectors: 11

# 6. Dashboard is reachable
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501/
# expect: 200

# 7. Pytest still green
pytest tests/ -q --no-cov
# expect: 695 passed
```

---

## 6. Common Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: src` after uvicorn launch | Working directory is wrong | Run uvicorn from the project root, or ensure `/opt/nifty100` is on `PYTHONPATH`. The app already inserts `PROJECT_ROOT` into `sys.path`, so this usually means a bad cwd. |
| `sqlite3.OperationalError: unable to open database file` | `DB_PATH` is relative & the process cwd != project root | Use absolute paths in `.env` (Option B step 2.3). |
| Dashboard says "cannot reach API" | Dashboard default assumes API on same host/port | Set `API_BASE_URL` env var to `http://host:8000/api/v1` (see docker-compose example). |
| PDFs show boxes instead of ₹ | Helvetica lacks the rupee glyph | By design — code uses `"Rs"` prefix. To show ₹, register a DejaVu or Noto font in ReportLab. |
| Tearsheet generation takes >30 s per batch | First run pays matplotlib font-cache cost | Warm cache by generating one tearsheet first; subsequent runs are ~1 s/PDF. |
| `make load` fails with `FileNotFoundError: profitandloss.xlsx` | `data/raw/` missing or wrong `RAW_DATA_DIR` | Confirm `RAW_DATA_DIR=data/raw` in `.env` and that all 7 Excel files are present. |
| API slow on first request (hundreds of ms) | Cold start, no indexes | Ensure Day-43 indexes are created: `python scripts/day43_indexes.py`. Subsequent requests drop to <10 ms p95. |
| 502 behind Nginx | uvicorn not listening on 127.0.0.1:8000 | Verify systemd service started; `sudo journalctl -u nifty-api -n 100`. |

---

## 7. Useful One-Liners

```bash
# Tail API logs
tail -f /var/log/nifty100/api.log

# Restart both services after a pull
cd /opt/nifty100 && git pull && sudo systemctl restart nifty-api nifty-dashboard

# Run a one-off screener preset
source .venv/bin/activate
python -m scripts.run_screener --preset debt_free_blue_chip --limit 10

# Regenerate all reports
make report

# Export OpenAPI + Postman collection
curl -s http://localhost:8000/export/openapi.json  -o docs/openapi.json
curl -s http://localhost:8000/export/postman.json  -o docs/postman_collection.json

# DB backup
sqlite3 db/nifty100.db ".backup" "db/backups/nifty100-$(date +%F).db"
```

---

## 8. Ports Reference Cheat Sheet

| Service | Dev port | Prod (behind Nginx) |
|---------|----------|---------------------|
| FastAPI (uvicorn) | 8000 | 127.0.0.1:8000 → `/api/` |
| Streamlit dashboard | 8501 | 127.0.0.1:8501 → `/` |
| Swagger UI | 8000/docs | proxied at `/docs` |
| ReDoc | 8000/redoc | proxied at `/redoc` |
| Nginx | — | 80 / 443 |

---

If you need a cloud-specific guide (AWS ECS, Render, Fly.io, Railway,
Hetzner, Kubernetes manifests), say the word and I'll add it.
