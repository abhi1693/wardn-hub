# syntax=docker/dockerfile:1

FROM node:26.12.1-alpine3.24@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS base

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

FROM base AS deps

RUN apk upgrade --no-cache && apk add --no-cache ca-certificates

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

RUN apk upgrade --no-cache && apk add --no-cache ca-certificates tar \
  && rm -rf /usr/local/lib/node_modules/npm /opt/yarn-* \
  && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg \
  && addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 --ingroup nodejs --home /app nextjs

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
