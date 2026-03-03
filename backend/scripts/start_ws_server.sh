#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

./venv/bin/python -m uvicorn backend.app.ws_server:app --host 0.0.0.0 --port 8001 --reload
