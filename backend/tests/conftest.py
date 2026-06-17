from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def example_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "aiwall.yaml"
    config_path.write_text(
        """
server:
  host: 127.0.0.1
  port: 9090
providers:
  - name: ollama
    type: ollama
    base_url: http://localhost:11434
    models: ["llama*"]
policies:
  - name: block-secrets
    when: input.contains_secret
    action: block
logging:
  log_raw_prompts: false
""".strip()
    )
    return config_path


@pytest.fixture
async def client(example_config: Path):
    app = create_app(config_path=example_config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
