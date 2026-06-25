# Wardn Hub

Wardn Hub is an MCP server definition registry and submission product. It stores
server records, versioned `server.json`-compatible documents, submissions,
partner metadata, moderation state, and audit history.

Runtime execution is intentionally out of scope.

## Phase 0 Scaffold

This scaffold includes:

- FastAPI backend under `hub/backend`
- Health endpoints under `/api/v1/health/live` and `/api/v1/health/ready`
- `WARDN_HUB_` settings prefix
- Alembic migration shell
- OpenAPI JSON export with `python -m app.openapi`
- Pytest harness
- Next.js frontend under `hub/frontend`
- Orval config targeting the generated backend OpenAPI schema

## Phase 1 Registry API

Phase 1 adds the initial MCP server/version store:

- Public read endpoints under `/api/v1/mcp/servers`
- Admin version CRUD under `/api/v1/admin/mcp/servers`
- `mcp_servers` and `mcp_server_versions` models and Alembic migration
- `server.json`-compatible validation with MCPB package metadata allowed
- Latest-version behavior, soft delete, cursor pagination, search, and OpenAPI client generation

## Phase 2 Auth And Organizations

Phase 2 adds the identity and organization foundation:

- Bootstrap first local superuser at `/api/v1/users/bootstrap`
- Login/logout session cookie flow under `/api/v1/auth`
- Pluggable auth provider metadata under `/api/v1/auth/providers`
- User API token CRUD under `/api/v1/auth/api-tokens`
- Organizations, roles, and memberships under `/api/v1/organizations`
- System organization roles with explicit permission strings
- Registry admin routes protected by superuser authentication

## Phase 3 Submissions And Audit

Phase 3 adds the moderation workflow around registry publishing:

- Server submissions under `/api/v1/submissions`
- Draft, submit, withdraw, approve, reject, and publish state transitions
- Publishing an approved submission into the Phase 1 registry store
- Audit event persistence for submission lifecycle actions
- Superuser audit event listing under `/api/v1/audit/events`

## Phase 4 Trust Model

Phase 4 namespace claims are currently deferred. Server identifiers still use
stable `publisher/server` names, but namespace ownership workflows are not part
of the active product surface. Namespace models, migration, and service code are
retained for future activation, while namespace routes are intentionally not
mounted.

## Phase 5 Partner Support

Phase 5 adds partner organization metadata and server support records:

- Partner fields on organizations for status, tier, profile, and support contact
- Partner organization listing under `/api/v1/partners`
- Server support mappings under `/api/v1/partners/organizations/{organization_id}/server-support`
- Support levels for official, verified, compatible, and deprecated relationships
- Audit events for partner metadata and support record changes

## Phase 6 Registry Trust Metadata

Phase 6 exposes trust-plane data through registry read APIs:

- Owner and organization actor summaries on registry server/version responses
- Active partner support summaries on registry server/version responses
- Partner and support-level filters backed by partner support records

## Phase 7 Frontend Product Surface

Phase 7 adds the first usable browser experience:

- Operational app shell with registry, submissions, partners, and audit views
- Registry browse/detail workflow with trust and partner support badges
- Protected data views for moderation queues, partner support, and audit records
- Same-origin frontend API proxy with optional direct `NEXT_PUBLIC_API_BASE_URL`
- Provider-aware sign-in/sign-up UI for local auth and Clerk

## Phase 8 Frontend Auth And Operator Actions

Phase 8 makes the console operable:

- Login, logout, and bearer token fallback controls
- Submission submit, withdraw, approve, reject, and publish actions
- Partner activation and server support creation controls

## Commands

```sh
cd hub/backend
cp .env.example .env
uv run --extra dev python -m app.openapi --output ../frontend/openapi/wardn-hub-api.json
uv run --extra dev python -m app.manage seed-categories
uv run --extra dev pytest
```

```sh
npm install
npm run web:api:generate
npm run web:dev
```

```sh
docker build -t wardn-hub-backend -f hub/backend/Dockerfile hub/backend
docker build -t wardn-hub-frontend -f hub/frontend/Dockerfile .
```

The frontend image follows the Shipyard-style deployment pattern: it ships the
source tree and installed dependencies, then builds `.next` with the runtime
environment before starting. In Kubernetes, run `hub/frontend/docker-build-next.sh`
from the image in a prebuild/init job with `.next` mounted on a shared volume,
then start the web container with:

```sh
node .next/standalone/hub/frontend/server.js
```

The default container command runs that build-and-start flow automatically.

## Public Release Checklist

- Use PostgreSQL and run Alembic migrations before serving traffic.
- Set `WARDN_HUB_ENVIRONMENT` to a non-local value such as `production`.
- Replace `WARDN_HUB_SESSION_SECRET` and `WARDN_HUB_API_TOKEN_SECRET` with
  independent, high-entropy values of at least 32 characters.
- Set `WARDN_HUB_CORS_ORIGINS` to the deployed frontend origin. Wildcard CORS is
  rejected outside local/test environments.
- Set `WARDN_HUB_REGISTRY_PUBLIC_BASE_URL` to the public frontend base URL.
- Set `WARDN_HUB_API_INTERNAL_BASE_URL` for frontend deployments where the
  backend is not reachable at `http://localhost:8000` from the Next.js server.
- Set `NEXT_PUBLIC_API_BASE_URL` only when browser clients should call the
  backend directly. If omitted, the browser client uses same-origin `/api/v1`
  and the Next.js rewrite proxies those requests to `WARDN_HUB_API_INTERNAL_BASE_URL`.
- Keep local email/password auth enabled with `WARDN_HUB_AUTH_PROVIDERS=local`.
  To enable Clerk alongside local auth, set `WARDN_HUB_AUTH_PROVIDERS=local,clerk`
  and `NEXT_PUBLIC_AUTH_PROVIDERS=local,clerk`.
- For Clerk, set `WARDN_HUB_CLERK_ISSUER` to the issuer used in Clerk session
  JWTs. Leave `WARDN_HUB_CLERK_AUDIENCE` empty when using Clerk's default session
  token. If you require an audience, configure a Clerk JWT template that emits
  that `aud` value, set `WARDN_HUB_CLERK_AUDIENCE` to the same value, and set
  `NEXT_PUBLIC_CLERK_JWT_TEMPLATE` to the template name so the frontend requests
  the correct token. Set `WARDN_HUB_CLERK_SECRET_KEY` if the backend must fetch
  the user's primary email from Clerk because the token does not include `email`
  or `email_address`.
- Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and server-side `CLERK_SECRET_KEY` for
  the frontend when Clerk is enabled. Do not prefix the secret key with
  `NEXT_PUBLIC_`.
- Google Analytics loads only in production. The frontend defaults to
  `G-GYYSYTBZTD`; set `GOOGLE_ANALYTICS_ID` to override the measurement ID.
