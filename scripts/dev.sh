#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AIWALL_CONFIG="${AIWALL_CONFIG:-$ROOT/aiwall.yaml.example}"
export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${AIWALL_PORT:-8080}" \
  --reload
