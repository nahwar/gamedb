# BUILD STAGE

FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --no-cache --no-dev --locked

# PROD

FROM python:3.12-alpine AS production

WORKDIR /app

COPY --from=builder /app/.venv ./.venv

COPY main.py ./

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]