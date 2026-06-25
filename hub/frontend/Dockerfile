FROM node:24-bookworm-slim AS deps

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
COPY hub/frontend/package.json ./hub/frontend/package.json
RUN npm ci

FROM deps AS builder

ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY hub/frontend ./hub/frontend
WORKDIR /app/hub/frontend
RUN npm run build

FROM node:24-bookworm-slim AS runner

WORKDIR /app/hub/frontend
ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN groupadd --system --gid 1001 nodejs && \
    useradd --system --uid 1001 --gid nodejs --home /app nextjs

COPY --from=builder --chown=nextjs:nodejs /app/hub/frontend/.next/standalone /app/
COPY --from=builder --chown=nextjs:nodejs /app/hub/frontend/.next/static ./.next/static

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
