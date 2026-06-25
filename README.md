# AIWall

Self-hosted AI security gateway for homelabs, developers, and teams.

AIWall sits between your applications and AI providers and gives you visibility, policy enforcement, secret scanning, audit logging, and cost tracking — on your own hardware, without paying for big-tech cloud solutions.

> AIWall is to AI traffic what Firewalla is to home networks.

## Status

**Early development.** This repository is being built toward the AIWall Community MVP: an OpenAI-compatible proxy with secret scanning, policy enforcement, and a local web control panel.

| Component | Status |
|---|---|
| FastAPI skeleton + `/healthz` + config loader | Done (Phase 1.1) |
| OpenAI-compatible proxy (`/v1/chat/completions`, SSE streaming) | Done (Phase 1.2) |
| Ollama adapter + provider router | Done (Phase 1.3) |
| Audit logging (SQLite) | Done (Phase 1.4) |
| Secret scanning | Planned |
| Policy engine (allow / warn / block) | Planned |
| Web control panel (dashboard, policy toggles, logs) | Planned |
| Alerts (Telegram / webhook / ntfy) | Planned |
| Docker Compose deployment | Planned |

## What AIWall Does

- **Proxies AI API traffic** — drop-in OpenAI-compatible endpoint for clients, scripts, and coding tools (Cursor, Claude Code, Continue.dev)
- **Scans for secrets** — detect API keys, tokens, SSH keys, and `.env` content before they reach a provider
- **Enforces policies** — allow, warn, block, or redact based on rules you can toggle from the GUI
- **Shows everything in a web control panel** — dashboard, event log, model usage, cost breakdown, policy management
- **Alerts you** — Telegram, webhook, or ntfy notification when something risky is blocked
- **Logs decisions** — privacy-preserving audit trail (raw prompts logged only if you opt in)
- **Tracks cost** — token counts and estimated spend by provider and model

## What AIWall Does Not Do

AIWall governs traffic from clients you control — anything with a configurable base URL or that you self-host. It **cannot** monitor or control commercial chatbot apps on phones (ChatGPT app, Character.AI, Gemini): those use pinned TLS certificates with no configurable endpoint. On-device app control belongs to Apple Screen Time, Google Family Link, and MDM tools.

## Family Use (Self-Hosted)

If you run your own AI stack, AIWall supports household profiles: give a child an account on your self-hosted chat UI (e.g. Open WebUI) routed through AIWall, with per-profile policies, daily limits, and usage summaries. The parent controls the client, so no traffic interception is needed.

## Editions

| Edition | License | Audience |
|---|---|---|
| **AIWall Community** | Apache-2.0 (this repo) | Homelab users, developers, self-hosters |
| **AIWall Pro** | Commercial | Power users, small teams, consultants |
| **AIWall Enterprise** | Commercial | Regulated organizations, security teams |

Community edition is designed to be genuinely useful on its own. Pro and Enterprise features ship as separate modules.

## Related Repositories

| Repository | Purpose |
|---|---|
| [AIWall](https://github.com/MohsenBah/AIWall) | Core product — proxy, policies, control panel |
| [AIWall-detections](https://github.com/MohsenBah/AIWall-detections) | Wazuh rules, Sigma rules, Grafana dashboards, SIEM content |
| [AIWall-redteam](https://github.com/MohsenBah/AIWall-redteam) | Adversarial testing payloads and mitigation validation |

## Quick Start

Not yet available. The first milestone is a Docker Compose deployment that proxies requests, blocks secret leaks, and shows events on the local control panel. Proxmox LXC/VM deployment guide will follow.

### Development (Phase 1.1)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/dev.sh
curl http://127.0.0.1:8080/healthz
```

Copy `aiwall.yaml.example` to `aiwall.yaml` to customize providers and policies.

Follow this repo for updates.

## Architecture (Planned)

```text
AI Application (script, coding tool, Open WebUI, ...)
    |
    v
AIWall Proxy
    |
    +-- Policy Engine
    +-- Secret Scanner
    +-- Cost Estimator
    +-- Provider Router
    +-- Audit Logger ----> Web Control Panel + Alerts (Telegram/webhook)
    |
    v
AI Provider (OpenAI-compatible, Ollama, ...)
```

**Stack:** Python 3.12, FastAPI, SQLite, Jinja2 + HTMX control panel, Docker.

## Configuration (Planned)

Clients point their base URL to AIWall:

```text
http://aiwall-host:8080/v1
```

Policies and providers are configured in `aiwall.yaml` and can be toggled from the web control panel.

## Contributing

Contributions are welcome once the project scaffold lands. External contributions will use a Developer Certificate of Origin (DCO) sign-off — no CLA required.

## License

[Apache License 2.0](LICENSE)

## Background

AIWall builds on ideas explored in [MedSecLab](https://github.com/MohsenBah/MedSecLab) — a simulated healthcare AI security lab — and productizes them for homelab, developer, and enterprise use.
