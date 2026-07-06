#!/usr/bin/env bash
# Demo AIWall proxy + policy enforcement against a running instance (Phase 1.10a).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${AIWALL_BASE_URL:-http://127.0.0.1:${AIWALL_PORT:-8080}}"
DB_PATH="${AIWALL_DB:-${ROOT}/data/aiwall.db}"
SECRET_SAMPLE="AKIAIOSFODNN7EXAMPLE"

info() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

pick_model() {
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'aiwall-ollama'; then
    echo "llama3.2:1b"
    return
  fi
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'aiwall'; then
    echo "gpt-4o-mini"
    return
  fi
  local ollama_url="${OLLAMA_URL:-http://127.0.0.1:11434}"
  if curl -sf "${ollama_url}/api/tags" >/dev/null 2>&1; then
    echo "llama3.2:1b"
    return
  fi
  echo "gpt-4o-mini"
}

require_aiwall() {
  if ! curl -sf "${BASE_URL}/healthz" >/dev/null; then
    echo "AIWall is not reachable at ${BASE_URL}" >&2
    echo "Start it with ./scripts/dev.sh or docker compose -f deploy/docker-compose.yml up" >&2
    exit 1
  fi
}

send_allow_request() {
  local model="$1"
  info "Sending normal request (model=${model})"
  curl -sS -w "\nHTTP %{http_code}\n" \
    "${BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    ${OPENAI_API_KEY:+-H "Authorization: Bearer ${OPENAI_API_KEY}"} \
    -d "{\"model\":\"${model}\",\"messages\":[{\"role\":\"user\",\"content\":\"hello from aiwall demo\"}]}"
  echo
}

send_block_request() {
  info "Sending secret-leak request (expect policy block)"
  curl -sS -w "\nHTTP %{http_code}\n" \
    "${BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"gpt-4o-mini\",\"messages\":[{\"role\":\"user\",\"content\":\"my aws key is ${SECRET_SAMPLE}\"}]}"
  echo
}

print_audit_rows() {
  info "Recent audit rows"
  local query="SELECT id, provider, model, decision, reason, total_tokens, estimated_cost, latency_ms FROM audit_events ORDER BY id DESC LIMIT 5;"

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'aiwall'; then
    docker exec aiwall python -c '
import sqlite3

conn = sqlite3.connect("/app/data/aiwall.db")
rows = conn.execute(
    "SELECT id, provider, model, decision, reason, total_tokens, estimated_cost, latency_ms "
    "FROM audit_events ORDER BY id DESC LIMIT 5"
).fetchall()
if not rows:
    print("(no rows)")
else:
    print("id | provider | model | decision | reason | tokens | cost | latency_ms")
    for row in rows:
        print(" | ".join("" if value is None else str(value) for value in row))
'
    return
  fi

  if command -v sqlite3 >/dev/null 2>&1 && [[ -f "${DB_PATH}" ]]; then
    sqlite3 -header -column "${DB_PATH}" "${query}"
    return
  fi

  warn "Could not read audit DB at ${DB_PATH}"
  echo "Open the dashboard: ${BASE_URL}/"
}

main() {
  require_aiwall
  local model
  model="$(pick_model)"
  if [[ "${model}" == "gpt-4o-mini" && -z "${OPENAI_API_KEY:-}" ]]; then
    warn "Ollama not detected and OPENAI_API_KEY is unset; allow request may log decision=error"
  fi

  send_allow_request "${model}"
  send_block_request
  print_audit_rows

  info "Done. Dashboard: ${BASE_URL}/"
}

main "$@"
