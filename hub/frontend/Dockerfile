# syntax=docker/dockerfile:1

FROM node:26.12.1-bookworm-slim@sha256:28147155d47dc31abe0a46e0d12b59b2fb3d0a2dcc5dc65fce76a074180b16fe AS base

ENV DEBIAN_FRONTEND=noninteractive \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

FROM base AS deps

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
COPY packages/braces ./packages/braces
COPY hub/frontend/package.json ./hub/frontend/package.json
RUN npm ci --ignore-scripts

FROM base AS runner

ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    WARDN_HUB_API_INTERNAL_BASE_URL=http://localhost:8000

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs --home /app nextjs

COPY --from=deps --chown=nextjs:nodejs /app ./
COPY --chown=nextjs:nodejs hub/frontend ./hub/frontend

RUN install -d -o nextjs -g nodejs /app/hub/frontend/.next \
  && chmod +x /app/hub/frontend/docker-build-next.sh /app/hub/frontend/docker-entrypoint.sh

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER nextjs
WORKDIR /app/hub/frontend
EXPOSE 3000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["web"]
