FROM ubuntu:24.04

ARG APP_VERSION=0.0.0
ARG CODEX_VERSION=0.142.3
ARG NODE_MAJOR=24

ENV DEBIAN_FRONTEND=noninteractive \
    CODEX_WORKDIR=/tmp/codex-work \
    HOME=/tmp/codex-user \
    NO_UPDATE_NOTIFIER=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    TMPDIR=/tmp/codex-tmp

RUN install -d -m 1777 /tmp/codex-tmp && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gnupg \
      jq \
      python3 \
      bubblewrap \
      git \
      ripgrep && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    printf 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_%s.x nodistro main\n' "$NODE_MAJOR" \
      > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install --global --no-audit --no-fund --no-update-notifier "@openai/codex@${CODEX_VERSION}" && \
    codex --version && \
    bwrap --version && \
    jq --version && \
    rg --version && \
    python3 --version && \
    install -d -m 0777 /workspace /tmp/codex-work /tmp/codex-user /codex-home /codex-auth && \
    rm -rf /var/lib/apt/lists/*

COPY codex-app-server-wrapper /usr/local/bin/codex-app-server-wrapper
RUN chmod 0755 /usr/local/bin/codex-app-server-wrapper

WORKDIR /tmp/codex-work

LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.title=wardn-hub-codex-app-server \
      org.opencontainers.image.description="Wardn Hub Codex app-server runtime image"

EXPOSE 41237

ENTRYPOINT ["/usr/local/bin/codex-app-server-wrapper"]
