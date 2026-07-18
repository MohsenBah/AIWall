# AIWall Architecture

This document describes the Community MVP architecture as shipped in Phase 1.

## Overview

AIWall is a self-hosted AI security gateway. Client applications send OpenAI-compatible requests to AIWall; AIWall evaluates policies, scans for secrets, logs the decision, and forwards allowed traffic to upstream providers (OpenAI-compatible APIs, Ollama, etc.).

```text
Client (curl, Cursor, Open WebUI, script)
    |
    v
AIWall (FastAPI)
    |
    +-- Policy Engine      allow / warn / block
    +-- Secret Scanner     regex on request body
    +-- Cost Estimator     prices.yaml + token usage
    +-- Provider Router    model -> provider
    +-- Audit Logger       SQLite
    +-- Web Dashboard      Jinja2 + HTMX at /
    |
    v
Upstream provider (OpenAI, Ollama, ...)
```

## Request flow

1. **Ingress** — `POST /v1/chat/completions` receives the request body and headers (including `Authorization` when present).
2. **Model extraction** — the `model` field is parsed from the JSON body.
3. **Provider selection** — the first configured provider whose `models` patterns match the requested model is chosen (`fnmatch` globs such as `gpt-*`, `llama*`).
4. **Policy evaluation** — policies from `aiwall.yaml` are evaluated in order:
   - `block` on first match stops the request (HTTP 403).
   - `redact` masks matched secrets in the request body, then continues.
   - `warn` is recorded but the request continues.
   - otherwise the request is allowed.
5. **Secret scan** — regex and entropy rules run on message content before forwarding; results feed `input.contains_secret` policies.
6. **Cost estimate (pre-forward)** — prompt tokens and `max_tokens` hints are used to estimate cost for `estimated_cost` policy conditions.
7. **Forward** — non-streaming: full upstream response; streaming: SSE chunks passed through to the client.
8. **Audit** — every request writes a row to SQLite (`decision`, `reason`, tokens, estimated cost, latency, redaction count).

Blocked requests never reach the upstream provider. Redacted requests reach the provider with secrets masked.

## Components

| Package | Role |
|---|---|
| `app/proxy/` | OpenAI-compatible forwarding, token/cost accounting |
| `app/policies/` | YAML policy engine with hot reload on each request |
| `app/scanners/` | Regex and entropy-based secret detection |
| `app/providers/` | Provider adapters and model-based routing |
| `app/audit/` | SQLite audit event model and writer |
| `app/storage/` | Database engine and schema migrations |
| `app/web/` | Server-rendered dashboard (Jinja2 + HTMX) |
| `app/config.py` | Pydantic models for `aiwall.yaml` |

## Exposed endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible proxy (streaming and non-streaming) |
| `/v1/models` | GET | Models from configured providers (OpenAI list shape) |
| `/healthz` | GET | Liveness, version, provider/policy counts |
| `/` | GET | Dashboard — summary cards and recent events |
| `/partials/events` | GET | HTMX fragment for filtered event table |
| `/partials/events/{id}/detail` | GET | HTMX fragment for privacy-safe event detail (rule ids, reason) |
| `/static/*` | GET | Dashboard CSS |

Clients should set their OpenAI base URL to:

```text
http://<aiwall-host>:8080/v1
```

## Streaming (SSE)

- Request bodies are read fully before forwarding so input policies and secret scanning run on the complete prompt.
- Streaming responses pass SSE chunks through to the client.
- Token usage for streams is computed from SSE `delta.content` chunks or a trailing `usage` object when the provider sends one.
- Audit rows for streams are written when the response finishes.

## Data storage

- **Audit events** — SQLite at the path configured in `logging.store` (default `sqlite:///data/aiwall.db`).
- **Configuration** — `aiwall.yaml` on disk; re-read by the policy engine on each evaluation.
- **Pricing** — `prices.yaml` beside the config file (or path set in `pricing.file`).

Raw prompts and responses are **not** stored unless `logging.log_raw_prompts: true`. When enabled, any detected secrets are masked as `[REDACTED:<rule_id>]` before persistence. Block responses list matched `rule_ids` and never echo the raw secret.

Secret detector inventory and the positive/negative test corpus are documented in [secret-scanning.md](secret-scanning.md).

## Deployment

| Mode | How |
|---|---|
| Docker Compose | `deploy/docker-compose.yml` — recommended |
| Local dev | `./scripts/dev.sh` with Python venv |
| Demo | `./scripts/demo.sh` against a running instance |

The Docker image runs as a non-root `aiwall` user, serves uvicorn on port 8080 (configurable via `AIWALL_PORT`), and bundles a default Docker-oriented config at `/app/aiwall.yaml`.

## Technology stack

- Python 3.12
- FastAPI + uvicorn
- httpx (async upstream proxy)
- SQLAlchemy + SQLite
- Jinja2 + HTMX (dashboard)
- Docker / Docker Compose

## Related repositories

| Repo | Purpose |
|---|---|
| [AIWall-detections](https://github.com/MohsenBah/AIWall-detections) | SIEM rules and dashboards |
| [AIWall-redteam](https://github.com/MohsenBah/AIWall-redteam) | Adversarial test payloads |
