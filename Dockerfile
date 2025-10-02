FROM python:3.10-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv sync --no-cache --no-dev --frozen

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]