# AIWall Configuration

AIWall reads a single YAML file (`aiwall.yaml` by default). Override the path with the `AIWALL_CONFIG` environment variable.

## File locations

| Environment | Default config path |
|---|---|
| Local dev | `./aiwall.yaml` (copy from `aiwall.yaml.example`) |
| Docker | `/app/aiwall.yaml` (mount or edit `deploy/examples/aiwall.docker.yaml`) |

Pricing defaults to `prices.yaml` in the same directory as the config file. Copy `prices.yaml.example` to get started.

## Full example

```yaml
server:
  host: 0.0.0.0
  port: 8080

providers:
  - name: openai
    type: openai-compatible
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    models: ["gpt-*"]

  - name: ollama
    type: ollama
    base_url: http://127.0.0.1:11434   # Docker Compose: http://ollama:11434
    models: ["llama*", "mistral*", "qwen*"]

policies:
  - name: block-secrets
    when: input.contains_secret
    action: block

  - name: warn-large-cost
    when: estimated_cost > 1.00
    action: warn

logging:
  store: sqlite:///data/aiwall.db
  log_raw_prompts: false
  retention_days: 90

pricing:
  file: prices.yaml

gateway_auth:
  enabled: false
  api_key_env: AIWALL_API_KEY
```

## Schema reference

### `server`

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | `0.0.0.0` | Bind address (uvicorn uses `0.0.0.0` in Docker/dev scripts) |
| `port` | integer | `8080` | Config file port hint; runtime port is set by `AIWALL_PORT` / uvicorn |

### `providers` (list)

Each provider entry:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Identifier used in audit logs and pricing |
| `type` | string | yes | `openai-compatible` or `ollama` |
| `base_url` | string | yes | Upstream API base URL |
| `api_key_env` | string | no | Environment variable name for the upstream API key |
| `models` | list of strings | no | `fnmatch` patterns; first matching provider wins |

**Provider types**

| `type` | Upstream URL built as |
|---|---|
| `openai-compatible` | `{base_url}/chat/completions` |
| `ollama` | `{base_url}/v1/chat/completions` |

**Model routing** — request `model` is matched against each provider's `models` list in file order. Example: `gpt-4o-mini` matches `gpt-*` on the `openai` provider.

### `presets` (list of strings)

Named policy packs merged before explicit `policies`. Shipped presets:

| Name | Behavior |
|---|---|
| `developer` | Warn on `input.contains_secret`; block on `input.contains_private_key` |
| `child` | For `user.role == "child"`: block `explicit`/`unsafe`/`violence` categories; hard-block secrets and private keys |

```yaml
presets:
  - developer
```

Preset files live in `presets/` (and are also packaged under `app/presets/`). Explicit policies with the same `name` override the preset entry.

### `policies` (list)

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | yes | Policy ID in audit logs and block responses |
| `when` | string | yes | Condition expression (see below) |
| `action` | string | yes | `allow`, `warn`, `block`, or `redact` |
| `enabled` | boolean | `true` | Skip when `false` |

**Evaluation order**

1. Enabled policies are scanned in file order (presets first, then explicit policies).
2. First matching `block` stops immediately (HTTP 403).
3. First matching `redact` is remembered; secrets are masked and the request continues.
4. First matching `warn` is remembered; request continues.
5. Precedence is `block` > `redact` > `warn` > `allow`.

**Supported `when` expressions**

| Expression | Meaning |
|---|---|
| `input.contains_secret` | Secret scanner found a match in the request |
| `input.contains_private_key` | Matched rule is an SSH/PKCS#8/encrypted private key |
| `user.role == "child"` | Authenticated profile role equals `child` (also `!=`) |
| `input.category == "explicit"` | Prompt classified into a content category |
| `input.category in ["unsafe", "explicit"]` | Prompt matches any listed category |
| `input.length > N` | Total message character length (comparison operators: `>`, `<`, `>=`, `<=`, `==`) |
| `estimated_cost > N` | Pre-request cost estimate from tokens + `prices.yaml` |

Combine atoms with `and`, for example:

```yaml
when: user.role == "child" and input.category in ["explicit", "unsafe"]
```

`user.role` is set from the profile that owns the Bearer API key. Requests without a profile identity (shared admin key or no auth) have no role, so role conditions do not match.

Built-in categories (keyword classifier): `explicit`, `violence`, `unsafe`.

Named presets:

| Preset | Purpose |
|---|---|
| `developer` | Warn on secrets; block private keys |
| `child` | Block risky categories for children; hard-block secrets/private keys for child roles |

Examples:

```yaml
when: input.contains_secret
when: input.length > 50000
when: estimated_cost > 0.50
```

Cost-based policies use a pre-forward estimate (prompt tokens + `max_tokens` / `max_completion_tokens` hint). Actual cost is recorded in the audit log after the response.

### `logging`

| Field | Type | Default | Description |
|---|---|---|---|
| `store` | string | `sqlite:///data/aiwall.db` | SQLite database URL |
| `log_raw_prompts` | boolean | `false` | Store prompt/response text in audit rows (opt-in). Detected secrets are always masked as `[REDACTED:<rule_id>]` before storage |
| `retention_days` | integer | `90` | Reserved for future retention jobs (not enforced in MVP) |

### `pricing`

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | string | `prices.yaml` | Path relative to the config file directory |

### `scanners`

| Field | Type | Default | Description |
|---|---|---|---|
| `ignore_examples` | boolean | `true` | Skip known documentation placeholders (e.g. `AKIAIOSFODNN7EXAMPLE`, repetitive `sk_test_` samples) |
| `entropy.enabled` | boolean | `true` | Detect high-entropy base64/hex-like strings |
| `entropy.min_length` | integer | `20` | Minimum candidate token length |
| `entropy.threshold` | float | `4.5` | Shannon entropy threshold (bits per character) |
| `dotenv.enabled` | boolean | `true` | Detect pasted `.env` bodies and credential dumps |
| `dotenv.min_lines` | integer | `2` | Minimum dotenv-style `KEY=value` lines to treat as a block |
| `dotenv.min_value_length` | integer | `8` | Minimum value length for dotenv/assignment lines |
| `dotenv.pasted_file_min_lines` | integer | `5` | Minimum assignment lines for large pasted config dumps |
| `allowlist.literals` | list of strings | `[]` | Exact matched values to ignore |
| `allowlist.patterns` | list of strings | `[]` | Regex patterns; matched secret substrings that match are ignored |
| `rules.<rule_id>.enabled` | boolean | `true` | Enable or disable a specific detector (including `high-entropy`) |
| `rules.<rule_id>.min_length` | integer | rule default | Minimum matched substring length before flagging |

When regex rules do not match, entropy detection flags long random-looking tokens (unknown API key formats). Disable or raise `threshold` if you see false positives.

**False-positive tuning:** set `ignore_examples: true` (default) for docs/tutorials, add project-specific `allowlist` entries, or disable noisy rules under `rules`. The test suite measures false-positive rate on `backend/tests/fixtures/scanner_corpus_negative.txt` and expects ≤ 5% on that corpus.

## `prices.yaml`

```yaml
models:
  openai:
    gpt-4o-mini:
      input_per_million: 0.15
      output_per_million: 0.60
    gpt-4o:
      input_per_million: 2.50
      output_per_million: 10.00
```

Costs are USD per million tokens. Unknown models return `null` estimated cost in audit logs.

### `gateway_auth`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Require a client API key before proxying `/v1/*` routes |
| `api_key_env` | string | `AIWALL_API_KEY` | Environment variable holding the expected client key |

When enabled, clients must send `Authorization: Bearer <key>` where `<key>` is either:

- the shared admin key from `AIWALL_API_KEY`, or
- a per-profile key issued via `ProfileStore.issue_api_key()` (prefix `aiwall_pk_`)

The gateway validates the key and does **not** forward it upstream; provider keys still come from each provider's `api_key_env` (e.g. `OPENAI_API_KEY`).

Profile keys are stored as SHA-256 hashes only. A successful profile-authenticated request sets audit `user_id` to the profile id.

### Daily usage limits

Profiles may set optional daily caps:

| Field | Unit | Behavior |
|---|---|---|
| `daily_request_limit` | count | Block after this many billable requests today |
| `daily_token_limit` | tokens | Block when today's tokens (plus projected request) would exceed the cap |
| `daily_cost_limit` | USD | Block when today's estimated cost (plus projected request) would exceed the cap |

`None` / unset means no cap. Billable decisions are `allow`, `warn`, and `redact` (policy blocks and upstream errors do not consume the request quota).

The reset window is the **UTC calendar day** (midnight UTC). Over-limit requests return HTTP 403 with `error.reason` / `error.policy` set to `daily-limit`.

Leave disabled for trusted localhost / homelab networks. Enable when exposing AIWall beyond your LAN. Even with auth disabled, presenting a valid profile key still attributes the request to that profile.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AIWALL_CONFIG` | `aiwall.yaml` | Path to configuration file |
| `AIWALL_PORT` | `8080` | HTTP listen port |
| `OPENAI_API_KEY` | _(unset)_ | Used when a provider sets `api_key_env: OPENAI_API_KEY` |
| `AIWALL_API_KEY` | _(unset)_ | Shared admin client key when `gateway_auth.enabled: true` (profile keys also accepted) |
| `OLLAMA_PORT` | `11434` | Host port for Ollama in Docker Compose (`--profile ollama`) |

Provider-specific keys are read from the environment variable named in `api_key_env`.

## Secret scanner

The built-in scanner runs on request message content. Rules include:

| Rule ID | Detects |
|---|---|
| `aws-access-key` | AWS access key IDs (`AKIA…`) |
| `github-token` | GitHub personal/access tokens |
| `github-fine-grained-token` | GitHub fine-grained tokens |
| `slack-token` | Slack bot/user tokens (`xox…`) |
| `stripe-secret-key` | Stripe secret keys (`sk_live_`, `sk_test_`) |
| `stripe-restricted-key` | Stripe restricted keys (`rk_live_`, `rk_test_`) |
| `google-api-key` | Google API keys (`AIza…`) |
| `azure-storage-key` | Azure storage account keys |
| `gcp-service-account` | GCP service account JSON |
| `database-url` | Database URLs with embedded credentials |
| `ssh-private-key` | PEM SSH private keys |
| `pkcs8-private-key` | PKCS#8 private keys |
| `encrypted-private-key` | Encrypted PEM private keys |
| `jwt` | JSON Web Token shape |
| `generic-api-key` | `api_key=…`, `secret_key=…`, etc. |
| `dotenv-secret` | Pasted `.env` bodies / credential dumps (includes assignment `count`) |
| `high-entropy` | Long high-entropy base64/hex-like strings |

Wire into policy with `when: input.contains_secret` and `action: block` (or `redact` / `warn`).

`action: redact` masks matched secrets in message content as `[REDACTED:<rule_id>]` before forwarding. The audit row uses `decision: redact` and stores `redaction_count`.

### Block / warn privacy

Blocked secret responses are structured and never echo the raw credential:

```json
{
  "error": {
    "message": "Request blocked by AIWall policy: block-secrets",
    "type": "policy_blocked",
    "code": "policy_blocked",
    "policy": "block-secrets",
    "reason": "secret-detected",
    "rule_ids": ["aws-access-key"]
  }
}
```

Warn and redact responses continue to the provider and add privacy-safe headers:

| Header | Meaning |
|---|---|
| `X-AIWall-Policy-Action` | `warn` or `redact` |
| `X-AIWall-Rule-Ids` | Comma-separated matched rule ids |

Audit rows store `matched_rule_ids` (no raw secret values).

### Tuning false positives

- **`ignore_examples`** (default `true`) — skips AWS doc keys, `EXAMPLE` placeholders, and repetitive `sk_test_` / `xoxb-` tutorial values.
- **`allowlist.literals` / `allowlist.patterns`** — project-specific values or regexes to ignore.
- **`rules.<rule_id>`** — disable a detector or raise `min_length` for noisy rules like `generic-api-key`.

The negative corpus at `backend/tests/fixtures/scanner_corpus_negative.txt` is checked in CI; the suite expects a false-positive rate ≤ 5%.

## Client setup

Point any OpenAI-compatible client to AIWall:

```text
Base URL:  http://127.0.0.1:8080/v1
API key:   your upstream key (or `AIWALL_API_KEY` when gateway auth is enabled)
```

Example:

```bash
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'
```

## Docker notes

- Bind-mount your config: `./my-aiwall.yaml:/app/aiwall.yaml:ro`
- Audit DB persists in the `aiwall_data` volume at `/app/data/aiwall.db`
- Use `http://ollama:11434` for Ollama when running the `ollama` Compose profile
- See `deploy/.env.example` for port and secret templates

## See also

- [Architecture](architecture.md) — request flow and components
- [Secret scanning](secret-scanning.md) — detectors, privacy, and test corpus
- [README](../README.md) — quick start
- `aiwall.yaml.example` — local development template
- `presets/developer.yaml` — developer guardrail policy pack
- `deploy/examples/aiwall.docker.yaml` — Docker Compose template
