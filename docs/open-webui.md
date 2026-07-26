# Open WebUI + AIWall (family reference)

Point each household Open WebUI account at AIWall with its own profile API key so child policies, daily limits, and audit attribution apply.

## Quick start

From the **repository root**:

```bash
cp deploy/.env.example .env
# Set AIWALL_API_KEY to a strong shared admin key (not a profile key).
# Optionally set OPENAI_API_KEY for gpt-* models.

docker compose -f deploy/examples/docker-compose.open-webui.yml --profile ollama up --build -d
```

| Service | URL |
|---|---|
| Open WebUI | http://127.0.0.1:3000 |
| AIWall dashboard | http://127.0.0.1:8080/ |
| AIWall OpenAI base | http://127.0.0.1:8080/v1 |

The family config (`aiwall.family.yaml`) enables `gateway_auth`, loads the `child` and `developer` presets, and allows CORS from the Open WebUI origin so **Direct Connections** work in the browser.

Pull a local model if you used `--profile ollama`:

```bash
docker compose -f deploy/examples/docker-compose.open-webui.yml exec ollama ollama pull llama3.2
```

## Map Open WebUI users → AIWall profiles

AIWall does not read Open WebUI's user database. Mapping is done by giving each person an **AIWall profile key** and configuring that key in Open WebUI.

### 1. Create a profile and issue a key

```bash
docker compose -f deploy/examples/docker-compose.open-webui.yml exec aiwall \
  python /app/scripts/issue_profile_key.py \
  --db sqlite:///data/aiwall.db \
  --name Kid \
  --role child \
  --daily-request-limit 40
```

Save the printed `aiwall_pk_…` key once. Repeat for adults (`--role adult`) or developers (`--role developer`).

### 2. Create matching Open WebUI accounts

In Open WebUI (first user becomes admin): create a login for each household member.

### 3. Preferred: per-user Direct Connections

So each chat account is enforced by its own AIWall profile:

1. Admin → **Settings → Connections → Direct Connections** → enable (already on via `ENABLE_DIRECT_CONNECTIONS` in the compose file).
2. As each user: **Settings → Connections → Add Connection**
   - **URL:** `http://127.0.0.1:8080/v1` (browser must reach the host port, not the Docker service name `aiwall`)
   - **API Key:** that user's `aiwall_pk_…` profile key
3. Select a model from that connection and send a message.

Traffic path: browser → AIWall (profile identity) → Ollama / OpenAI.

### 4. Optional: shared admin connection

Compose also sets Open WebUI's server-side OpenAI URL to `http://aiwall:8080/v1` with `AIWALL_API_KEY`. That path is for admin/bootstrap only — it is **not** per-profile. Use Direct Connections for family enforcement.

## Verify enforcement

As the child user, ask for something the child preset blocks (for example explicit content). Expect HTTP 403 from AIWall and a blocked row on http://127.0.0.1:8080/blocked filtered to that profile.

Check attribution:

```bash
curl -s http://127.0.0.1:8080/reports/weekly
```

## Files

| Path | Role |
|---|---|
| `deploy/examples/docker-compose.open-webui.yml` | Compose stack |
| `deploy/examples/aiwall.family.yaml` | Auth + child preset + CORS |
| `scripts/issue_profile_key.py` | Create profile / rotate key |
| `deploy/.env.example` | Ports and secrets |

## Proxmox / LAN notes

- Publish `AIWALL_PORT` and `OPEN_WEBUI_PORT` on the VM; point Direct Connections at `http://<vm-lan-ip>:8080/v1`.
- Add that origin to `cors.allow_origins` in `aiwall.family.yaml` (for example `http://192.168.1.50:3000`) and recreate the AIWall container.
- Do not expose AIWall to the public internet without TLS and a strong `AIWALL_API_KEY`.
