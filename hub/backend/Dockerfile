# syntax=docker/dockerfile:1

FROM python:3.13.17-slim-trixie@sha256:fe14fd57a4c0361110eaa0c284112b189750bcb43fb04bb5d1ee7b7744027ccf AS python

# Headless, installer-free application runtime. uv creates the project venv.
RUN python -m pip uninstall --yes pip setuptools wheel && \
    rm -rf /usr/local/lib/python3.13/tkinter /usr/local/lib/python3.13/idlelib \
      /usr/local/lib/python3.13/turtledemo /usr/local/lib/python3.13/ensurepip && \
    rm -f /usr/local/lib/python3.13/turtle.py \
      /usr/local/lib/python3.13/__pycache__/turtle.* \
      /usr/local/lib/python3.13/lib-dynload/_tkinter.* /usr/local/bin/idle*

FROM node:26.12.1-trixie-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec AS codex
ARG CODEX_VERSION=0.163.0
RUN npm install --prefix /opt/codex --no-audit --no-fund "@openai/codex@${CODEX_VERSION}" && \
    /opt/codex/node_modules/.bin/codex --version

# Build only the locked upstream CEL helper with a patched native Go toolchain.
# The SDK is mounted during dependency installation and is absent at runtime.
FROM golang:1.27.3-trixie@sha256:fbb7ae40b62ff8afe31662df570d39b4f5052ac32b90dae8e60d7657a20a74f4 AS go

FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944 AS runtime-base

ARG DEBIAN_FRONTEND=noninteractive
# Bootstrap HTTPS from the pinned official donor, then use Ubuntu's own signed
# CA and OS packages. Copy no Debian OS libraries or package databases.
COPY --from=python /etc/ssl/certs/ca-certificates.crt /tmp/apt-bootstrap-ca.pem
RUN sed -i -E 's@http://(archive.ubuntu.com/ubuntu|security.ubuntu.com/ubuntu|ports.ubuntu.com/ubuntu-ports)@https://\1@g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get -o Acquire::https::CaInfo=/tmp/apt-bootstrap-ca.pem update && \
    apt-get -o Acquire::https::CaInfo=/tmp/apt-bootstrap-ca.pem dist-upgrade -y --no-install-recommends && \
    apt-get -o Acquire::https::CaInfo=/tmp/apt-bootstrap-ca.pem install -y --no-install-recommends \
      ca-certificates tzdata libssl3t64 libdb5.3t64 libbz2-1.0 libffi8 libgdbm6t64 \
      liblzma5 libncursesw6 libtinfo6 libreadline8t64 libsqlite3-0 libuuid1 zlib1g \
      libstdc++6 libatomic1 libgomp1 curl git jq && \
    if [ -e /usr/bin/pebble ]; then \
      if dpkg-query -S /usr/bin/pebble >/dev/null 2>&1; then \
        echo 'Unexpected package-owned Pebble; review runtime removal policy' >&2; exit 1; \
      fi; \
      rm /usr/bin/pebble; \
    fi && \
    rm -f /tmp/apt-bootstrap-ca.pem && rm -rf /var/lib/apt/lists/*
COPY --from=python /usr/local/ /usr/local/
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /opt/codex/node_modules/@openai /opt/codex/node_modules/@openai
RUN ldconfig && \
    ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && \
    python --version && node --version && codex --version && \
    python -c 'import ssl,bz2,sqlite3,ctypes,dbm.gnu,dbm.ndbm,lzma,curses,readline,uuid,venv; from zoneinfo import ZoneInfo; assert ZoneInfo("UTC"); assert ssl.create_default_context().get_ca_certs()'

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM runtime-base AS runner
COPY --from=uv /uv /uvx /bin/
ENV PATH="/app/.venv/bin:${PATH}" \
    HOME="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN groupadd --system --gid 999 app && \
    useradd --system --uid 999 --gid app --home /app app && \
    mkdir -p /app/.cache && chown app:app /app /app/.cache
COPY --chown=app:app pyproject.toml uv.lock ./
USER app
RUN --mount=type=bind,from=go,source=/usr/local/go,target=/usr/local/go \
    --mount=type=cache,id=hub-cel-go1273,target=/app/.cache/go,uid=999,gid=999 \
    --mount=type=cache,id=hub-cel-gomod,target=/app/.cache/gomod,uid=999,gid=999 \
    --mount=type=cache,target=/app/.cache/uv,uid=999,gid=999 \
    PATH="/usr/local/go/bin:$PATH" GOTOOLCHAIN=local \
    GOCACHE=/app/.cache/go GOMODCACHE=/app/.cache/gomod \
    uv sync --frozen --no-dev --no-install-project --no-binary-package cisco-ai-skill-scanner
COPY --chown=app:app . .
RUN --mount=type=bind,from=go,source=/usr/local/go,target=/usr/local/go \
    --mount=type=cache,id=hub-cel-go1273,target=/app/.cache/go,uid=999,gid=999 \
    --mount=type=cache,id=hub-cel-gomod,target=/app/.cache/gomod,uid=999,gid=999 \
    --mount=type=cache,target=/app/.cache/uv,uid=999,gid=999 \
    PATH="/usr/local/go/bin:$PATH" GOTOOLCHAIN=local \
    GOCACHE=/app/.cache/go GOMODCACHE=/app/.cache/gomod \
    uv sync --frozen --no-dev --no-editable --no-binary-package cisco-ai-skill-scanner && \
    mkdir -p /app/.codex
ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
