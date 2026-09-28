FROM python:3.14.7-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir "uv>=0.12,<0.13"
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN uv sync --no-dev --no-editable

FROM python:3.14.7-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN groupadd --system taskiller && useradd --system --gid taskiller --home /app taskiller
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

USER taskiller
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health/live', timeout=3).read()"

CMD ["sh", "-c", "python scripts/migrate.py && exec uvicorn taskiller.main:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"]
