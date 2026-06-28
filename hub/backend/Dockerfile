FROM ghcr.io/astral-sh/uv:0.11.13 AS uv
FROM node:24-bookworm-slim AS codex

ARG CODEX_VERSION=0.142.3
RUN npm install -g @openai/codex@${CODEX_VERSION} && \
    codex --version

FROM python:3.13-slim-bookworm

COPY --from=uv /uv /uvx /bin/
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

ENV PATH="/app/.venv/bin:${PATH}" \
    HOME="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project && \
    codex --version && \
    mkdir -p /app/.codex && \
    chown -R app:app /app

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER app
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
