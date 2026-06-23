# Wardn Hub

Wardn Hub is a private MCP server definition registry. It stores server records,
versioned `server.json`-compatible documents, submissions, namespace ownership,
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

## Commands

```sh
cd hub/backend
uv run --extra dev python -m app.openapi --output ../frontend/openapi/wardn-hub-api.json
uv run --extra dev pytest
```

```sh
npm install
npm run web:api:generate
npm run web:dev
```
