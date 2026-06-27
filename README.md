# Wardn Hub

[![Tests](https://github.com/abhi1693/wardn-hub/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/abhi1693/wardn-hub/actions/workflows/tests.yml)
[![Security Checks](https://github.com/abhi1693/wardn-hub/actions/workflows/security.yml/badge.svg?branch=master)](https://github.com/abhi1693/wardn-hub/actions/workflows/security.yml)
[![Container Image](https://github.com/abhi1693/wardn-hub/actions/workflows/container.yml/badge.svg)](https://github.com/abhi1693/wardn-hub/actions/workflows/container.yml)

Wardn Hub is a registry and submission product for Model Context Protocol (MCP)
server definitions. It gives users a browser experience for discovering published
MCP server records and gives maintainers a structured workflow for submitting
`server.json`-compatible metadata for review and publication.

Wardn Hub stores definitions, version history, ownership metadata, partner support
metadata, moderation state, and audit history. It does not run MCP servers,
install workspace MCP configuration, invoke MCP tools, or provide a gateway
execution plane.

## Product Capabilities

- Browse published MCP servers, categories, server owners, documentation, package
  targets, remote endpoints, versions, and partner support badges.
- Submit new MCP servers and new versions through a guided web form, with API
  support for additional submission types such as metadata edits and takedown
  appeals.
- Import a submission draft from a GitHub repository by reading repository
  metadata, `server.json`, `mcp.json`, and README content where available.
- Track draft, submitted, approved, rejected, withdrawn, and published submission
  states.
- Support local email/password authentication, optional Clerk authentication,
  HTTP session cookies, and scoped user API tokens.
- Manage organizations, memberships, roles, partner organizations, partner support
  records, categories, users, and audit events with role-based access controls.
- Publish approved submissions into the public registry store with versioned MCP
  server records.

## Architecture

This repository follows the Wardn AI monorepo layout:

```text
hub/
  backend/    FastAPI API, SQLAlchemy models, Alembic migrations, tests
  frontend/   Next.js web app, generated OpenAPI client, UI components
```

Key conventions:

- Backend API prefix: `/api/v1`
- Backend settings prefix: `WARDN_HUB_`
- Backend framework: FastAPI on Python 3.12+
- Database: PostgreSQL through SQLAlchemy async sessions and Alembic migrations
- Frontend framework: Next.js 16 and React 19
- API client generation: OpenAPI export plus Orval

## User-Facing App

The web app includes these primary views:

- `Explore`: public registry listing for published MCP servers.
- `Categories`: category directory and category-specific server listings.
- `Servers`: server detail pages with documentation, packages, remotes, version
  data, owner data, and partner support metadata.
- `Submit`: guided submission builder for package-based and remote MCP servers.
- `Submissions`: draft and review workflow for submitters and moderators.
- `Partners`: partner organization and server support management.
- `Users`: public registry user directory, with additional admin controls for
  superusers.
- `Account API Tokens`: token creation and management for API access.
- `Audit`: superuser audit event listing.

The submission builder supports package targets for UVX, npm, PyPI, OCI images,
Docker images, and MCPB packages. It also supports remote targets using
streamable HTTP or SSE metadata.

The frontend calls the API through same-origin `/api/v1` by default. The Next.js
rewrite proxies those requests to `WARDN_HUB_API_INTERNAL_BASE_URL`, which
defaults to `http://localhost:8000`. Set `NEXT_PUBLIC_API_BASE_URL` only when the
browser should call the backend directly.

## API Overview

Interactive API docs are available from a running backend at:

- Swagger UI: `http://localhost:8000/api/v1/docs`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

Important route groups:

| Area | Routes |
| --- | --- |
| Health | `GET /api/v1/health/live`, `GET /api/v1/health/ready` |
| Auth | `/api/v1/auth/providers`, `/api/v1/auth/login`, `/api/v1/auth/register`, `/api/v1/auth/logout`, `/api/v1/auth/me`, `/api/v1/auth/api-tokens` |
| Users | `/api/v1/users`, `/api/v1/users/bootstrap`, `/api/v1/users/{user_id}` |
| Organizations | `/api/v1/organizations`, roles, and memberships |
| Registry | `/api/v1/mcp/servers`, `/api/v1/mcp/catalog`, `/api/v1/mcp/categories` |
| Admin registry | `/api/v1/admin/mcp/servers` |
| Imports | `POST /api/v1/imports/server-source` |
| Submissions | `/api/v1/submissions` and lifecycle actions |
| Partners | `/api/v1/partners` and server support records |
| Audit | `GET /api/v1/audit/events` |

Registry server documents use stable `publisher/server` identifiers, semantic
versions, at least one category, and at least one package target or remote target.
Package metadata can describe registry type, package identifier, package version,
transport command, arguments, environment variables, and package arguments.
Remote metadata can describe endpoint URL, transport type, headers, query
parameters, and authentication hints.

## Local Development

### Prerequisites

- Python 3.12 or newer. CI currently runs Python 3.13.
- [uv](https://docs.astral.sh/uv/) for backend dependency management.
- Node.js 24 and npm.
- A running PostgreSQL database.

This repository does not include a docker compose file. Start PostgreSQL with
your preferred local setup and point `WARDN_HUB_DATABASE_URL` at it.

### Backend

```sh
cd hub/backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run python -m app.manage seed-categories
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

After the database is migrated, create the first superuser:

```sh
curl -X POST http://localhost:8000/api/v1/users/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "change-this-password",
    "first_name": "Admin",
    "last_name": "User"
  }'
```

The bootstrap endpoint succeeds only while no user exists. Later calls return a
conflict response.

### Frontend

From the repository root:

```sh
npm install
npm run web:api:generate
npm run web:dev
```

Open the app at `http://localhost:3000`.

## Configuration

Backend settings are loaded from environment variables with the `WARDN_HUB_`
prefix. `hub/backend/.env.example` contains the local defaults.

| Variable | Purpose |
| --- | --- |
| `WARDN_HUB_ENVIRONMENT` | Environment name. Use `local` for development and a non-local value such as `production` for releases. |
| `WARDN_HUB_API_PREFIX` | API prefix. Defaults to `/api/v1`. |
| `WARDN_HUB_DATABASE_URL` | PostgreSQL SQLAlchemy URL, for example `postgresql+asyncpg://user:password@localhost:5432/wardn_hub`. |
| `WARDN_HUB_CORS_ORIGINS` | Comma-separated browser origins allowed by the backend. |
| `WARDN_HUB_SESSION_SECRET` | Secret used for signed session cookies. Must be high entropy in production. |
| `WARDN_HUB_API_TOKEN_SECRET` | Secret used for API token signing. Must be independent from the session secret in production. |
| `WARDN_HUB_API_TOKEN_PREFIX` | Prefix used when issuing user API tokens. |
| `WARDN_HUB_SESSION_COOKIE_NAME` | Cookie name for local session auth. |
| `WARDN_HUB_SESSION_TTL_SECONDS` | Session lifetime in seconds. |
| `WARDN_HUB_REGISTRY_PUBLIC_BASE_URL` | Public frontend base URL used in registry links. |
| `WARDN_HUB_AUTH_PROVIDERS` | Comma-separated auth providers. Supported values are `local` and `clerk`. |
| `WARDN_HUB_AUTH_DEFAULT_PROVIDER` | Default auth provider. Must be enabled in `WARDN_HUB_AUTH_PROVIDERS`. |
| `WARDN_HUB_CLERK_ISSUER` | Required outside local/test when Clerk auth is enabled. |
| `WARDN_HUB_CLERK_JWKS_URL` | Optional Clerk JWKS override. |
| `WARDN_HUB_CLERK_AUDIENCE` | Optional Clerk JWT audience. |
| `WARDN_HUB_CLERK_SECRET_KEY` | Optional backend Clerk secret for fetching profile data not present in JWTs. |

Frontend settings:

| Variable | Purpose |
| --- | --- |
| `WARDN_HUB_API_INTERNAL_BASE_URL` | Backend URL reached by the Next.js server-side proxy. Defaults to `http://localhost:8000`. |
| `NEXT_PUBLIC_API_BASE_URL` | Optional browser-visible backend URL. If unset, the browser uses same-origin `/api/v1`. |
| `NEXT_PUBLIC_AUTH_PROVIDERS` | Auth providers exposed to the frontend. Defaults to `local`. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Enables Clerk UI integration when Clerk is listed in `NEXT_PUBLIC_AUTH_PROVIDERS`. |
| `NEXT_PUBLIC_CLERK_JWT_TEMPLATE` | Optional Clerk JWT template requested by the frontend. |
| `CLERK_SECRET_KEY` | Server-side Clerk secret used by the Next.js integration. Do not expose it with a `NEXT_PUBLIC_` prefix. |
| `GOOGLE_ANALYTICS_ID` | Optional production Google Analytics measurement ID. A default ID is used in production if unset. |

Production settings reject placeholder secrets, secrets shorter than 32
characters, and wildcard CORS origins.

## Common Commands

From the repository root:

```sh
npm run api:openapi       # Export backend OpenAPI JSON
npm run web:api:generate  # Regenerate the frontend API client
npm run web:lint          # Lint the frontend
npm run web:build         # Build the frontend
npm run backend:lint      # Run ruff against the backend
npm run backend:test      # Run backend tests
```

Backend-only commands:

```sh
cd hub/backend
uv run alembic upgrade head
uv run python -m app.manage seed-categories
uv run python -m app.cli.review_pending_submissions --once --dry-run
uv run pytest
uv run ruff check .
```

Regenerate the frontend API client after changing backend routes, schemas, or
OpenAPI metadata.

### Pending Submission Review CLI

Submitted MCP server reviews can be assisted by an LLM while keeping moderation
actions human-driven:

```sh
cd hub/backend
WARDN_HUB_TOKEN=wardn_hub_key... uv run python -m app.cli.review_pending_submissions \
  --url https://hub.example.com/api/v1 \
  --model gpt-5 \
  --thinking xhigh
```

The token must authenticate a superuser or global moderator and should include
`submissions:read` and `submissions:moderate`; publishing also requires a
superuser token with `submissions:publish`. The default review command is Codex:

```sh
codex exec --sandbox read-only --skip-git-repo-check -
```

Override it with `--review-command` or `WARDN_HUB_REVIEW_COMMAND`. The prompt is
sent on stdin unless the command includes `{prompt_file}`. The CLI fetches the
first submitted review, sends submission context to the LLM, shows the findings,
then waits for a human action: approve, approve and publish, reject with message,
skip, or quit.

Use `--model` or `WARDN_HUB_REVIEW_MODEL` to pass a model to the default
`codex exec` reviewer. Use `--thinking` or `WARDN_HUB_REVIEW_THINKING` to pass
one of `low`, `medium`, `high`, or `xhigh` as Codex reasoning effort. For other
LLM CLIs, include the equivalent model/thinking flags directly in
`--review-command`.

If `--url` is omitted, the CLI uses `WARDN_HUB_API_BASE_URL` or local
`http://localhost:8000/api/v1`.
The CLI sends `WardnHubReviewCLI/0.1` as its HTTP user agent by default; override
it with `--user-agent` or `WARDN_HUB_USER_AGENT` if an edge proxy requires a
specific API-client signature.

## Containers

Build images locally:

```sh
docker build -t wardn-hub-backend -f hub/backend/Dockerfile hub/backend
docker build -t wardn-hub-frontend -f hub/frontend/Dockerfile .
```

The backend image exposes port `8080` and runs:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The frontend image exposes port `3000`. Its entrypoint builds the Next.js
standalone output with runtime environment variables, copies static assets into
the standalone bundle, and starts:

```sh
node .next/standalone/hub/frontend/server.js
```

On GitHub release publication, the container workflow publishes linux/arm64
images to GitHub Container Registry:

- `ghcr.io/abhi1693/wardn-hub/backend`
- `ghcr.io/abhi1693/wardn-hub/frontend`

Release tags include the semantic release version and `latest`.

## CI And Security

GitHub Actions currently includes:

- `Tests`: backend dependency install with uv, ruff linting, pytest, frontend npm
  install, frontend linting, and frontend production build.
- `Security Checks`: gitleaks secret scanning, `npm audit` for production
  frontend dependencies, and `pip-audit` for backend dependencies.
- `Container Image`: release-triggered backend and frontend container image
  builds and pushes.

## Public Release Checklist

- Use PostgreSQL and run Alembic migrations before serving traffic.
- Set `WARDN_HUB_ENVIRONMENT` to a non-local value such as `production`.
- Replace `WARDN_HUB_SESSION_SECRET` and `WARDN_HUB_API_TOKEN_SECRET` with
  independent high-entropy secrets of at least 32 characters.
- Set `WARDN_HUB_CORS_ORIGINS` to the deployed frontend origin.
- Set `WARDN_HUB_REGISTRY_PUBLIC_BASE_URL` to the public frontend base URL.
- Set `WARDN_HUB_API_INTERNAL_BASE_URL` for frontend deployments where the
  backend is not reachable at `http://localhost:8000` from the Next.js server.
- Enable only the intended auth providers with `WARDN_HUB_AUTH_PROVIDERS` and
  `NEXT_PUBLIC_AUTH_PROVIDERS`.
- If Clerk is enabled in production, configure `WARDN_HUB_CLERK_ISSUER` and the
  matching frontend Clerk environment variables.
- Bootstrap the first superuser, then use role-based access controls for
  moderators, partner managers, and superusers.

## Scope Boundaries

Wardn Hub is intentionally a registry and submission hub. Runtime execution is
out of scope for this repository:

- No workspace MCP installs.
- No MCP tool invocation routes.
- No Kubernetes runtime management.
- No gateway execution plane.

## License

No license file is currently included in this repository.
