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
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system taskiller && useradd --system --gid taskiller --home /app taskiller
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

USER taskiller
EXPOSE 8000

CMD ["uvicorn", "taskiller.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
