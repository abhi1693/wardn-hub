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
| Skills | `/api/v1/skills`, `/api/v1/skills/search`, `/api/v1/skills/official` |
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

Import skills from a GitHub repository:

```sh
cd hub/backend
uv run python -m app.manage skills import-github \
  https://github.com/acme/agent-skills \
  --subfolder skills/weather
```

Omit `--subfolder` to import every `SKILL.md` discovered in the repository. The
subfolder can point at one skill folder or a parent folder containing many
skills. The importer reads `name` and `description` from `SKILL.md` frontmatter
when available, stores text supporting files from the skill folder, and honors
`GITHUB_TOKEN` when set. Use `--ref` for a branch, tag, or commit SHA.

Import every skill under a repository subfolder:

```sh
cd hub/backend
uv run python -m app.manage skills import-github \
  https://github.com/anthropics/skills \
  --ref main \
  --subfolder skills
```

Mark an imported skills owner as official:

```sh
cd hub/backend
uv run python -m app.manage skills mark-official vercel-labs
```

Use `--unset` to remove official status from that source owner.

### Discover skills without syncing the catalog

Wardn Hub includes one agent-agnostic, API-native bootstrap skill at
`skills/find-skills`. An Agent Skills-compatible host with a POSIX shell,
`curl`, `jq`, and `mktemp` can use it to search the public Hub API and load one
selected `SKILL.md` for the current task without downloading the catalog.

The skill source is:

```text
https://github.com/abhi1693/wardn-hub/tree/master/skills/find-skills
```

For a POSIX manual installation, set `AGENT_SKILLS_DIR` to the host agent's
user-level skills directory.

```sh
(
: "${AGENT_SKILLS_DIR:?Set AGENT_SKILLS_DIR to the host agent's skills directory}"
case "${AGENT_SKILLS_DIR}" in
  /*) ;;
  *)
    echo "AGENT_SKILLS_DIR must be an absolute path" >&2
    exit 1
    ;;
esac
umask 077

if ! mkdir -p "${AGENT_SKILLS_DIR}"; then
  echo "Could not create the host agent's skills directory" >&2
  exit 1
fi
if ! AGENT_SKILLS_DIR="$(CDPATH= cd -P "${AGENT_SKILLS_DIR}" 2>/dev/null && pwd -P)"; then
  echo "Could not resolve the host agent's skills directory" >&2
  exit 1
fi
if [ "${AGENT_SKILLS_DIR}" = "/" ] || [ "${AGENT_SKILLS_DIR}" = "//" ]; then
  echo "AGENT_SKILLS_DIR must not resolve to the filesystem root" >&2
  exit 1
fi
SKILL_DIR="${AGENT_SKILLS_DIR}/find-skills"
TMP_DIR=""
LOCK_DIR=""
LOCK_PATH="${AGENT_SKILLS_DIR}.find-skills.lock"
MARKER_NAME=""

cleanup() {
  [ -z "${TMP_DIR}" ] || rm -rf "${TMP_DIR}"
  if [ -n "${LOCK_DIR}" ]; then
    rmdir "${LOCK_DIR}" 2>/dev/null || :
  fi
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

if ! mkdir "${LOCK_PATH}"; then
  echo "Another find-skills installation is active" >&2
  exit 1
fi
LOCK_DIR="${LOCK_PATH}"
if [ -e "${SKILL_DIR}" ] || [ -L "${SKILL_DIR}" ]; then
  echo "Skill already exists: ${SKILL_DIR}" >&2
  exit 1
fi

if ! TMP_DIR="$(mktemp -d "${AGENT_SKILLS_DIR}.find-skills.XXXXXX")"; then
  echo "Could not create a temporary skill directory" >&2
  exit 1
fi
TARGET_FILESYSTEM="$(df -P "${AGENT_SKILLS_DIR}" | awk 'NR == 2 { print $1 }')"
STAGING_FILESYSTEM="$(df -P "${TMP_DIR}" | awk 'NR == 2 { print $1 }')"
if [ -z "${TARGET_FILESYSTEM}" ] ||
  [ "${TARGET_FILESYSTEM}" != "${STAGING_FILESYSTEM}" ]; then
  echo "Staging and agent skills directories must share a filesystem" >&2
  exit 1
fi
MARKER_NAME=".install-${TMP_DIR##*/}"
if ! : >"${TMP_DIR}/${MARKER_NAME}"; then
  echo "Could not create the staged install marker" >&2
  exit 1
fi
if ! mkdir -p "${TMP_DIR}/scripts"; then
  echo "Could not create the staged skill layout" >&2
  exit 1
fi

download_file() {
  destination="$1"
  max_size="$2"
  url="$3"
  if ! status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 30 --max-filesize "${max_size}" \
    --output "${destination}" --write-out '%{http_code}' \
    --request GET \
    "${url}")"; then
    return 1
  fi
  [ "${status}" = "200" ]
}

if ! download_file \
  "${TMP_DIR}/commit.json" \
  262144 \
  https://api.github.com/repos/abhi1693/wardn-hub/commits/master; then
  echo "Could not resolve an immutable Wardn Hub revision" >&2
  exit 1
fi
if ! SKILL_REF="$(jq --exit-status --raw-output \
  '.sha | strings | select(test("^[0-9a-f]{40}$"))' \
  "${TMP_DIR}/commit.json")"; then
  echo "Wardn Hub returned an invalid revision" >&2
  exit 1
fi
if ! rm -f "${TMP_DIR}/commit.json"; then
  echo "Could not remove staged revision metadata" >&2
  exit 1
fi
RAW_ROOT="https://raw.githubusercontent.com/abhi1693/wardn-hub/${SKILL_REF}/skills/find-skills"

if ! download_file "${TMP_DIR}/SKILL.md" 131072 "${RAW_ROOT}/SKILL.md"; then
  echo "Could not download find-skills/SKILL.md" >&2
  exit 1
fi
if ! download_file \
  "${TMP_DIR}/scripts/wardn-skills.sh" \
  131072 \
  "${RAW_ROOT}/scripts/wardn-skills.sh"; then
  echo "Could not download find-skills/scripts/wardn-skills.sh" >&2
  exit 1
fi
if ! chmod 700 "${TMP_DIR}/scripts/wardn-skills.sh"; then
  echo "Could not make the Wardn resolver executable" >&2
  exit 1
fi

if [ -e "${SKILL_DIR}" ] || [ -L "${SKILL_DIR}" ]; then
  echo "Skill appeared during installation: ${SKILL_DIR}" >&2
  exit 1
fi
if ! mv "${TMP_DIR}" "${SKILL_DIR}"; then
  echo "Could not install find-skills" >&2
  exit 1
fi
if [ ! -f "${SKILL_DIR}/${MARKER_NAME}" ]; then
  NESTED_DIR="${SKILL_DIR}/${TMP_DIR##*/}"
  if [ -f "${NESTED_DIR}/${MARKER_NAME}" ]; then
    TMP_DIR="${NESTED_DIR}"
    if ! rm -rf "${TMP_DIR}"; then
      echo "Could not remove the nested staged install" >&2
      exit 1
    fi
  fi
  TMP_DIR=""
  echo "Skill target changed during installation" >&2
  exit 1
fi
TMP_DIR=""
if ! rm -f "${SKILL_DIR}/${MARKER_NAME}"; then
  echo "Could not remove the installed marker" >&2
  exit 1
fi
if ! rmdir "${LOCK_DIR}"; then
  echo "Could not release the installation lock" >&2
  exit 1
fi
LOCK_DIR=""
trap - HUP INT TERM
trap - 0
)
```

The resolver requires `curl`, `jq`, and `mktemp` and uses the pinned public API at
`https://hub.wardnai.dev/api/v1`. Discovery and reload behavior are determined
by the host agent.

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
| `WARDN_HUB_DATABASE_CLIENT_POOL_ENABLED` | Enables the application-side SQLAlchemy connection pool. Defaults to `true`; set to `false` when the database URL targets an external session pooler such as PgBouncer. |
| `WARDN_HUB_CORS_ORIGINS` | Comma-separated browser origins allowed by the backend. |
| `WARDN_HUB_SESSION_SECRET` | Secret used for signed session cookies. Must be high entropy in production. |
| `WARDN_HUB_API_TOKEN_SECRET` | Secret used for API token signing. Must be independent from the session secret in production. |
| `WARDN_HUB_SYSTEM_REVIEW_SECRET` | Optional shared secret for internal system review endpoints. Must be high entropy when set in production. |
| `WARDN_HUB_CODEX_APP_SERVER_URL` | Experimental Codex app-server WebSocket URL used by the submission review worker. |
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
| `WARDN_HUB_OTEL_ENABLED` | Enables OpenTelemetry tracing for the backend. Defaults to `false`. |
| `WARDN_HUB_OTEL_SERVICE_NAME` | Service name reported to the collector. Defaults to `wardn-hub-api`. |
| `WARDN_HUB_OTEL_SERVICE_NAMESPACE` | Service namespace reported as a resource attribute. Defaults to `wardn-hub`. |
| `WARDN_HUB_OTEL_RESOURCE_ATTRIBUTES` | Optional comma-separated OpenTelemetry resource attributes, for example `k8s.namespace.name=wardn,k8s.deployment.name=wardn-hub`. |
| `WARDN_HUB_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Optional OTLP HTTP traces endpoint. For the local k3s Grafana stack, use `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318/v1/traces`. |
| `WARDN_HUB_OTEL_EXPORTER_OTLP_TRACES_HEADERS` | Optional comma-separated OTLP exporter headers. Leave empty for the in-cluster collector. |
| `WARDN_HUB_OTEL_TRACES_SAMPLE_RATIO` | Trace sampling ratio from `0.0` to `1.0`. Defaults to `1.0`. |
| `WARDN_HUB_OTEL_EXCLUDED_URLS` | Optional comma-separated URL patterns excluded from FastAPI tracing. |

GitHub source imports also honor `GITHUB_TOKEN` when present, which avoids
unauthenticated GitHub API rate limits while reading repository metadata.

Frontend settings:

| Variable | Purpose |
| --- | --- |
| `WARDN_HUB_API_INTERNAL_BASE_URL` | Backend URL reached by the Next.js server-side proxy. Defaults to `http://localhost:8000`. |
| `NEXT_PUBLIC_SITE_URL` | Public frontend base URL used for canonical metadata, robots.txt, sitemap URLs, and llms.txt. Defaults to `https://hub.wardnai.dev` in production and `http://localhost:3000` locally. |
| `NEXT_PUBLIC_REGISTRY_PUBLIC_BASE_URL` | Browser-visible public registry URL used for generated README badge Markdown. Defaults to `https://hub.wardnai.dev`. |
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

Submitted MCP server reviews can be assisted by Codex app-server while keeping
moderation actions human-driven:

```sh
codex app-server --listen ws://127.0.0.1:41237

cd hub/backend
WARDN_HUB_CODEX_APP_SERVER_URL=ws://127.0.0.1:41237 \
uv run python -m app.cli.review_pending_submissions
```

The review worker requires `WARDN_HUB_CODEX_APP_SERVER_URL` or
`--codex-app-server-url`. It reads submitted submissions directly from the
configured database, oldest submitted first, and keeps reviewing until no
submitted records remain. It does not poll the Hub API, require submission
webhooks or event triggers, or spawn subprocess reviewers.

For long-running review automation, run Codex app-server separately and point the
review worker at it:

```sh
codex app-server --listen ws://127.0.0.1:41237

WARDN_HUB_CODEX_APP_SERVER_URL=ws://127.0.0.1:41237 \
uv run python -m app.cli.review_pending_submissions \
  --submission-id 00000000-0000-0000-0000-000000000000 \
  --non-interactive \
  --auto-reject \
  --auto-approve
```

Review mode does not spawn local Codex subprocesses or forward Wardn Hub
credentials into Codex; Codex uses the login state of the long-running
app-server process. The review thread is ephemeral, requests live web search,
and runs with read-only filesystem access plus network access.

The CLI uses the same validation prompt text as the web UI, including the
upstream source/release verification workflow. It loads the oldest submitted
review from the database, shows the findings, then waits for a human action:
approve, approve and publish, reject with message, skip, or quit.

When rejecting, the CLI reuses the LLM report's `Suggested rejection message`
section when one is present. If no suggested rejection message is available, it
prompts for one.

### Draft/Rejection Fix CLI

Draft and rejected MCP server submissions can be repaired with the same
Codex app-server setup:

```sh
codex app-server --listen ws://127.0.0.1:41237

cd hub/backend
WARDN_HUB_CODEX_APP_SERVER_URL=ws://127.0.0.1:41237 \
uv run python -m app.cli.fix_rejected_submissions
```

The fix worker reads eligible draft/rejected submissions directly from the
database, oldest updated first, and keeps running until no eligible records
remain. Eligibility is intentionally narrow: it only fixes submissions owned by
an active superuser or active partner organization. It does not call the Hub API,
forward Wardn Hub credentials to Codex, use event webhooks, or spawn subprocess
reviewers. Codex returns an updated `serverJson`; the worker validates it with
the Pydantic MCP server model and submits the same record for review.

Use `--verbose` to stream Codex app-server reviewer output while the review is
running. Findings are still shown again before the moderation prompt.

For automation, target one submission and avoid prompts:

```sh
WARDN_HUB_CODEX_APP_SERVER_URL=ws://127.0.0.1:41237 \
uv run python -m app.cli.review_pending_submissions \
  --submission-id 00000000-0000-0000-0000-000000000000 \
  --non-interactive \
  --auto-reject \
  --auto-approve
```

In non-interactive mode, `pass` can approve, `needs fixes` or `reject` can
reject when a suggested rejection message exists, and `cannot validate` or
ambiguous results leave the submission unchanged for manual review or a later
retry.

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
- Set `NEXT_PUBLIC_REGISTRY_PUBLIC_BASE_URL` to the public frontend base URL
  when generated README badge Markdown should point at a non-default domain.
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
