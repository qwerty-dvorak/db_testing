FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY main.py setup_db.py setup.sh ./
COPY scripts ./scripts
COPY sql ./sql

RUN pip install --no-cache-dir .

CMD ["python", "main.py", "status"]
