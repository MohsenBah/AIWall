# Deploy examples

| File | Purpose |
|---|---|
| `aiwall.docker.yaml` | Default single-service Compose config (`deploy/docker-compose.yml`) |
| `aiwall.family.yaml` | Family stack: gateway auth, child/developer presets, CORS for Open WebUI |
| `docker-compose.open-webui.yml` | AIWall + Open WebUI (+ optional Ollama profile) |

Start the family reference stack from the repository root:

```bash
docker compose -f deploy/examples/docker-compose.open-webui.yml --profile ollama up --build -d
```

Full walkthrough (profile keys, Direct Connections, verification): [docs/open-webui.md](../../docs/open-webui.md).
