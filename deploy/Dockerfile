# AIWall Community MVP — slim runtime image (Phase 1.9a)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIWALL_CONFIG=/app/aiwall.yaml \
    AIWALL_PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system aiwall \
    && useradd --system --gid aiwall --home-dir /app --no-create-home aiwall

COPY pyproject.toml README.md LICENSE ./
COPY backend ./backend

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY deploy/examples/aiwall.docker.yaml ./aiwall.yaml
COPY prices.yaml.example ./prices.yaml.example

RUN mkdir -p /app/data \
    && chown -R aiwall:aiwall /app

USER aiwall

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
