# AIWall

Local-first AI security gateway for families, developers, and teams.

AIWall sits between your applications and AI providers and gives you visibility, policy enforcement, secret scanning, audit logging, and cost tracking — without sending your traffic to a third-party cloud.

> AIWall is to AI traffic what Firewalla is to home networks.

## Status

**Early development.** This repository is being built toward the [AIWall Community MVP](https://github.com/MohsenBah/AIWall): an OpenAI-compatible proxy with secret scanning, policy enforcement, and a local dashboard.

| Component | Status |
|---|---|
| OpenAI-compatible proxy | Planned |
| Ollama provider support | Planned |
| Secret scanning | Planned |
| Policy engine (allow / warn / block) | Planned |
| Local dashboard | Planned |
| Docker Compose deployment | Planned |

## What AIWall Does

- **Proxies AI API traffic** — drop-in OpenAI-compatible endpoint for clients and tools
- **Scans for secrets** — detect API keys, tokens, SSH keys, and `.env` content before they reach a provider
- **Enforces policies** — allow, warn, block, or redact based on YAML rules
- **Logs decisions** — privacy-preserving audit trail (no raw prompts by default)
- **Tracks cost** — token counts and estimated spend by provider and model

## Editions

| Edition | License | Audience |
|---|---|---|
| **AIWall Community** | Apache-2.0 (this repo) | Home users, developers, homelab |
| **AIWall Pro** | Commercial | Families, small teams, consultants |
| **AIWall Enterprise** | Commercial | Regulated organizations, security teams |

Community edition is designed to be genuinely useful on its own. Pro and Enterprise features ship as separate modules.

## Related Repositories

| Repository | Purpose |
|---|---|
| [AIWall](https://github.com/MohsenBah/AIWall) | Core product — proxy, policies, dashboard |
| [AIWall-detections](https://github.com/MohsenBah/AIWall-detections) | Wazuh rules, Sigma rules, Grafana dashboards, SIEM content |
| [AIWall-redteam](https://github.com/MohsenBah/AIWall-redteam) | Adversarial testing payloads and mitigation validation |

## Quick Start

Not yet available. The first milestone is a Docker Compose deployment that proxies requests, blocks secret leaks, and shows events on a local dashboard.

Follow this repo for updates.

## Architecture (Planned)

```text
AI Application
    |
    v
AIWall Proxy
    |
    +-- Policy Engine
    +-- Secret Scanner
    +-- Cost Estimator
    +-- Provider Router
    +-- Audit Logger
    |
    v
AI Provider (OpenAI-compatible, Ollama, ...)
```

**Stack:** Python 3.12, FastAPI, SQLite, Jinja2 + HTMX dashboard, Docker.

## Configuration (Planned)

Clients point their base URL to AIWall:

```text
http://aiwall-host:8080/v1
```

Policies and providers are configured in `aiwall.yaml`. See the long-term plan for an example configuration.

## Contributing

Contributions are welcome once the project scaffold lands. External contributions will use a Developer Certificate of Origin (DCO) sign-off — no CLA required.

## License

[Apache License 2.0](LICENSE)

## Background

AIWall builds on ideas explored in [MedSecLab](https://github.com/MohsenBah/MedSecLab) — a simulated healthcare AI security lab — and productizes them for home, developer, and enterprise use.
