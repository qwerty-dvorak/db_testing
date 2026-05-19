FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY main.py setup_db.py setup.sh ./
COPY scripts ./scripts
COPY sql ./sql

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "main.py", "status"]
