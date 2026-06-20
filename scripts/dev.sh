#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AIWALL_CONFIG="${AIWALL_CONFIG:-${ROOT}/aiwall.yaml}"
if [[ ! -f "$AIWALL_CONFIG" ]]; then
  AIWALL_CONFIG="${ROOT}/aiwall.yaml.example"
  echo "Using example config: $AIWALL_CONFIG"
  echo "Copy to aiwall.yaml to customize (cp aiwall.yaml.example aiwall.yaml)"
fi
export AIWALL_CONFIG
export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${AIWALL_PORT:-8080}" \
  --reload
