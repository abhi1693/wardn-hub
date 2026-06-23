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
