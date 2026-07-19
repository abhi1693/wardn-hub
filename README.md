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
- Support local email/password authentication, optional generic OpenID Connect (OIDC),
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
  cli/        Publishable npm CLI for Wardn skill lifecycle management
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
| Auth | `/api/v1/auth/providers`, `/api/v1/auth/login`, `/api/v1/auth/register`, `/api/v1/auth/oidc/login`, `/api/v1/auth/oidc/callback`, `/api/v1/auth/logout`, `/api/v1/auth/me`, `/api/v1/auth/api-tokens` |
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

Import skills from active public GitHub repositories. The original positional
owner form remains available:

```sh
cd hub/backend
uv run python -m app.manage skills import-github \
  acme \
  --subfolder skills
```

The positional value must be a bare GitHub account login, not a repository URL.
For a filtered multi-target search, repeat `--owner`, `--org`, `--user`, and
`--repo` as needed:

```sh
uv run python -m app.manage skills import-github \
  --org anthropics \
  --org openai \
  --repo github/awesome-copilot \
  --min-stars 100 \
  --active-within-days 180 \
  --language Python \
  --topic agents \
  --subfolder skills
```

Use `--all-github` instead of target selectors to search globally. Broad scans
should normally include selective filters and a repository budget:

```sh
uv run python -m app.manage skills import-github \
  --all-github \
  --min-stars 50 \
  --active-within-days 365 \
  --verified-orgs-only \
  --max-repositories 5000
```

Supported repository filters are `--min-stars`, `--max-stars`,
`--active-within-days`, `--pushed-after`, `--pushed-before`, `--created-after`,
`--created-before`, `--language`, repeatable `--topic`, and
`--verified-orgs-only`. Date values accept ISO-8601 dates or datetimes.
`--max-repositories` stops discovery after that many matching active
repositories. `--all-github` cannot be combined with an owner, organization,
user, or repository target.

Discovery uses GitHub repository search and streams at most one 100-result page
at a time. GitHub exposes only the first 1,000 repositories for one search, so
unbounded scans automatically split the query into non-overlapping repository
creation-time windows instead of silently truncating results. The importer then
holds only the current repository tree and that repository's bounded skill
bundles in memory. A token is strongly recommended for broad scans because
GitHub applies separate search and API rate limits.

When GitHub returns a primary or secondary rate-limit response, the process
logs the affected resource and retry delay, sleeps, then retries the same HTTP
request without advancing the repository stream. Primary limits honor
`x-ratelimit-reset`; secondary limits honor `retry-after`, then
`x-ratelimit-reset`, and otherwise use an exponential delay starting at one
minute and capped at fifteen minutes. Repeated rate-limit responses continue to
wait and retry, so an operator can leave a long import running or terminate it
normally with an interrupt.

Private, forked, archived, and disabled repositories are excluded. If
`--subfolder` is supplied, the same path is scanned on every repository's
default branch. When it is omitted, the whole repository tree is scanned for
`SKILL.md`. Repositories without a matching skill are skipped normally;
matching repositories commit independently. The command returns a nonzero
status when no skills were imported, any repository failed, or any discovered
skill was invalid, even though successful repository commits are retained.
Authentication, non-rate-limit GitHub server, and transport failures stop the
remaining repository requests. When imported content changes, prior skill audit
results are cleared so the new snapshot must be audited again.

The subfolder can point at one skill folder or a parent folder containing many
skills. The importer reads `name` and `description` from `SKILL.md` frontmatter,
stores regular supporting files from the skill folder, and honors
`GITHUB_TOKEN` when set. UTF-8 files are stored as text; binary files are stored
as base64 with encoding metadata. Nested skill folders own their own files.
Dependency/build directories, symlinks, and gitlinks are excluded. A bundle may
contain up to 256 files, 8 MiB per file, and 16 MiB total. Each matching
repository is capped at 256 MiB across its discovered bundles; choose a narrower
`--subfolder` for larger repositories. Imported skills are additive: repositories
excluded or absent from a later owner scan are not unpublished.

Skill detail responses return only the root `SKILL.md` by default. Pass
`include_bundle=true` to retrieve its stored scripts, references, and assets:

```sh
curl --get \
  --data-urlencode 'include_bundle=true' \
  http://localhost:8000/api/v1/skills/acme/agent-skills/weather
```

Refresh every active GitHub skill from its recorded repository, branch, and
exact skill directory:

```sh
cd hub/backend
uv run python -m app.manage skills refresh
```

The refresh command updates snapshot bundles for existing skills only. It does
not discover new skills, change catalog metadata or visibility, or replace a
missing skill with a nested one. Only skills with the exact GitHub branch and
directory provenance recorded by `import-github` are fetched. Successful skills
commit independently; the command returns a nonzero status when any recorded
skill cannot be refreshed. Failed records keep their last snapshot and
publication state so transient GitHub failures cannot silently unpublish catalog
entries; review the structured failure logs. Changed snapshot hashes clear prior
skill audit results. When auditing is enabled, the refresh command immediately
runs the pending-audit queue so changed snapshots are rescanned before it exits.
The command uses `GITHUB_TOKEN` when present. Rate-limit responses sleep and retry
the same refresh request; authentication, non-rate-limit GitHub server, and
transport failures stop the remaining refresh requests.

When skill auditing is enabled, every `skills import-github` and `skills refresh`
command immediately runs the pending-audit queue after its GitHub phase finishes.
Successfully committed skills are audited even when another repository or skill
made the overall command return a failure. The command returns a nonzero status
if either its GitHub phase or its audit phase fails.

You can also manually audit every current public skill snapshot that does not
yet have a completed audit:

```sh
cd hub/backend
WARDN_HUB_SKILL_AUDIT_ENABLED=true uv run python -m app.manage skills audit
```

Skill auditing is disabled by default. Set `WARDN_HUB_SKILL_AUDIT_ENABLED=true`
on the API and import/refresh worker to expose results, automatically audit after
GitHub imports and refreshes, and allow the manual command to run. When disabled,
imports continue without scanning, catalog responses omit audit statuses, the UI
hides audit controls, and the audit endpoint does not expose stored results.
Skill-install telemetry is independent of this gate and remains unchanged.

The command streams one skill bundle from PostgreSQL at a time. It validates
safe materialization, then runs the pinned Cisco AI Skill Scanner locally with
its balanced policy, core static/YARA, bytecode, pipeline, and behavioral AST
analyzers. It never enables the scanner's meta, Cisco AI Defense, or VirusTotal
integrations. By default, the LLM analyzer is also disabled and bundle content
is not sent to a model. Opaque executables and malformed or
resolver-incompatible bundles fail before materialization.

Set `WARDN_HUB_SKILL_AUDIT_LLM_ENABLED=true` to add the scanner's semantic LLM
analyzer while the main audit gate is enabled. Configure the provider with the
scanner's standard `SKILL_SCANNER_LLM_PROVIDER`, `SKILL_SCANNER_LLM_MODEL`,
`SKILL_SCANNER_LLM_API_KEY`, `SKILL_SCANNER_LLM_BASE_URL`, and
`SKILL_SCANNER_LLM_API_VERSION` environment variables as required by the chosen
backend. When enabled, skill instructions and bundled source are sent to that
provider. The scanner result must report that `llm_analyzer` completed; missing
or failed LLM coverage leaves the skill unaudited. The gate and non-secret LLM
routing values are included in the audit configuration SHA-256, so changing the
provider, model, endpoint, API version, or temperature makes earlier results
stale. The API key is never included in that fingerprint.

Every result includes a deterministic security score from 0 to 100. Findings
are grouped by security category; every category deducts points based on its
highest severity, and additional findings in the category continue to deduct at
a reduced rate. Medium, high, and critical findings also enforce score ceilings
of 79, 49, and 24 so a severe issue cannot be hidden by otherwise clean files.
Scores use GitHub-profile-style ranks: `S` (99–100), `A+` (88–98), `A`
(75–87), `A-` (63–74), `B+` (50–62), `B` (38–49), `B-` (25–37), `C+`
(13–24), and `C` (0–12). Pass/warn/fail remains a separate compatibility and
security floor.

Each result is bound to the exact current snapshot ID and content hash, and each
skill commits independently. A later import or refresh that changes the bundle
invalidates its audit. Scanner version, policy fingerprint, analyzer set, and
normalizer version are persisted with the result. Changing the pinned audit
configuration makes prior rows ineligible until those snapshots are rescanned.
Restarting the command skips completed current snapshots and retries scanner
errors, so a long catalog audit is resumable without loading the catalog into
memory.

Use `--skill-id owner/repository/slug` for one skill, `--max-skills` to bound a
run, `--reaudit` to replace the current result for matching snapshots,
`--scanner-timeout` to bound each local scanner subprocess, and `--dry-run` to
run the complete scan without database writes. A dry run still calls the LLM
provider when its gate is enabled.

For example, import every skill under `skills` across an organization's active
repositories:

```sh
cd hub/backend
uv run python -m app.manage skills import-github \
  anthropics \
  --subfolder skills
```

Mark an imported skills owner as official:

```sh
cd hub/backend
uv run python -m app.manage skills mark-official vercel-labs
```

Use `--unset` to remove official status from that source owner.

### Manage agent skills with the npm CLI

The publishable `@wardn-ai/skills` workspace replaces the POSIX-only
`find-skills` support scripts. It now owns the full resolver workflow—search,
audit normalization, root inspection, hash-pinned temporary bundle fetches—and
marker-safe installation, update, and removal:

```sh
npx -y @wardn-ai/skills search "code audit" --limit 8 --json
npx -y @wardn-ai/skills audit owner/repository/skill-slug --json
npx -y @wardn-ai/skills inspect owner/repository/skill-slug --json
npx -y @wardn-ai/skills fetch-bundle owner/repository/skill-slug --json
npx @wardn-ai/skills install owner/repository/skill-slug -g -a codex
npx @wardn-ai/skills update skill-slug -g -a codex
npx @wardn-ai/skills remove skill-slug -g -a codex -y
```

The repository's `find-skills` skill is declarative: it invokes the latest release
of this npm package by default and contains no bundled resolver or self-installer
scripts. Append an exact version, such as `@wardn-ai/skills@0.1.6`, when a pinned
release is preferred.
Install or update that bootstrap skill through the same lifecycle command:

```sh
npx -y @wardn-ai/skills install abhi1693/wardn-hub/find-skills -g -a codex
```

Project installs are the default. Use `--global` for a user-level install,
repeat `--agent` for multiple hosts, or pass an explicit absolute skills
directory with `--target`. The initial built-in agent targets are Codex, Claude
Code, Cursor, OpenCode, Gemini CLI, GitHub Copilot, and the universal Agent
Skills directory.

The CLI preserves the resolver's security boundaries: it validates Wardn IDs,
snapshot hashes, root metadata, encodings, paths, file counts, and decoded byte
limits; refuses symlink and unmanaged-directory collisions; stages replacements
on the target filesystem; and retains the previous managed installation until
an update succeeds. A matching legacy `find-skills` installation created by the
former Wardn shell self-installer is migrated automatically; unrelated or
malformed directories remain untouched. `--hash` pins an install to an exact
audited or otherwise selected snapshot.

After a complete temporary bundle is materialized or a new installation succeeds,
the CLI sends one best-effort anonymous event with only the public skill ID,
content hash, CLI identifier, and CLI version. Set
`WARDN_HUB_DISABLE_TELEMETRY=1`, `DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, or use
`--no-telemetry` to opt out. Telemetry never includes local paths, source code,
task context, user identifiers, or device identifiers, and a telemetry failure
never fails or removes an installed bundle.

Publish `@wardn-ai/skills` independently from the Hub application version. Bump
`hub/cli/package.json`, then push `skills-v<version>` (for example,
`skills-v0.1.0`). The npm workflow can
also be dispatched manually from `master`; it validates the package metadata,
refuses an existing npm version, and publishes with provenance through npm
Trusted Publishing.

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
| `WARDN_HUB_SKILL_AUDIT_ENABLED` | Enables Cisco-backed post-import and manual skill audits, audit filtering, and audit result exposure. Defaults to `false`. |
| `WARDN_HUB_SKILL_AUDIT_LLM_ENABLED` | Adds the Cisco scanner's semantic LLM analyzer to enabled skill audits. Configure it with `SKILL_SCANNER_LLM_*` variables. Defaults to `false`. |
| `WARDN_HUB_CORS_ORIGINS` | Comma-separated browser origins allowed by the backend. |
| `WARDN_HUB_SESSION_SECRET` | Secret used for signed session cookies. Must be high entropy in production. |
| `WARDN_HUB_API_TOKEN_SECRET` | Secret used for API token signing. Must be independent from the session secret in production. |
| `WARDN_HUB_SYSTEM_REVIEW_SECRET` | Optional shared secret for internal system review endpoints. Must be high entropy when set in production. |
| `WARDN_HUB_CODEX_APP_SERVER_URL` | Experimental Codex app-server WebSocket URL used by the submission review worker. |
| `WARDN_HUB_API_TOKEN_PREFIX` | Prefix used when issuing user API tokens. |
| `WARDN_HUB_SESSION_COOKIE_NAME` | Cookie name for the signed application session. |
| `WARDN_HUB_SESSION_TTL_SECONDS` | Session lifetime in seconds. |
| `WARDN_HUB_REGISTRY_PUBLIC_BASE_URL` | Public frontend base URL used in registry links and to derive the default OIDC callback. |
| `WARDN_HUB_AUTH_PROVIDERS` | Comma-separated auth providers. Supported values are `local` and `oidc`. |
| `WARDN_HUB_AUTH_DEFAULT_PROVIDER` | Default auth provider. Must be enabled in `WARDN_HUB_AUTH_PROVIDERS`. |
| `WARDN_HUB_OIDC_PROVIDER_NAME` | Provider label shown on the sign-in screen. |
| `WARDN_HUB_OIDC_ISSUER_URL` | OIDC issuer used for discovery and ID-token validation. |
| `WARDN_HUB_OIDC_CLIENT_ID` | OIDC client identifier. |
| `WARDN_HUB_OIDC_CLIENT_SECRET` | OIDC client secret. Keep it on the backend only. |
| `WARDN_HUB_OIDC_REDIRECT_URI` | Optional callback override. Defaults to `{WARDN_HUB_REGISTRY_PUBLIC_BASE_URL}/api/auth/oidc/callback`. |
| `WARDN_HUB_OIDC_SCOPES` | Requested scopes. Include `openid`; the default also requests `email` and `profile`. |
| `WARDN_HUB_OIDC_STATE_COOKIE_NAME` | Cookie name prefix for short-lived OIDC state and nonce data. |
| `WARDN_HUB_OIDC_ALLOW_UNVERIFIED_EMAIL` | Allows an identity whose email is explicitly unverified. Defaults to `false`. |
| `WARDN_HUB_OIDC_AUTO_CREATE_USERS` | Creates a Hub user on the first permitted OIDC sign-in. |
| `WARDN_HUB_OIDC_ALLOWED_EMAIL_DOMAINS` | Optional comma-separated email-domain allowlist. Empty allows every domain. |
| `WARDN_HUB_OIDC_SUPERUSER_EMAILS` | Optional comma-separated emails promoted to Hub superusers after OIDC sign-in. |
| `WARDN_HUB_OTEL_ENABLED` | Enables OpenTelemetry tracing for the backend. Defaults to `false`. |
| `WARDN_HUB_OTEL_SERVICE_NAME` | Service name reported to the collector. Defaults to `wardn-hub-api`. |
| `WARDN_HUB_OTEL_SERVICE_NAMESPACE` | Service namespace reported as a resource attribute. Defaults to `wardn-hub`. |
| `WARDN_HUB_OTEL_RESOURCE_ATTRIBUTES` | Optional comma-separated OpenTelemetry resource attributes, for example `k8s.namespace.name=wardn,k8s.deployment.name=wardn-hub`. |
| `WARDN_HUB_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Optional OTLP HTTP traces endpoint. For the local k3s Grafana stack, use `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318/v1/traces`. |
| `WARDN_HUB_OTEL_EXPORTER_OTLP_TRACES_HEADERS` | Optional comma-separated OTLP exporter headers. Leave empty for the in-cluster collector. |
| `WARDN_HUB_OTEL_TRACES_SAMPLE_RATIO` | Trace sampling ratio from `0.0` to `1.0`. Defaults to `1.0`. |
| `WARDN_HUB_OTEL_EXCLUDED_URLS` | Optional comma-separated URL patterns excluded from FastAPI tracing. |
| `WARDN_HUB_PUBLIC_RATE_LIMIT_ENABLED` | Enables Valkey-backed public API and skill telemetry rate limiting. |
| `WARDN_HUB_SKILL_TELEMETRY_RATE_LIMIT_REQUESTS` | Maximum anonymous skill install events per client and telemetry window. Defaults to `20`. |
| `WARDN_HUB_SKILL_TELEMETRY_RATE_LIMIT_WINDOW_SECONDS` | Anonymous skill telemetry rate-limit window. Defaults to `60`. |
| `WARDN_HUB_SKILL_TELEMETRY_RATE_LIMIT_KEY_PREFIX` | Valkey key prefix for anonymous skill telemetry rate limits. |

GitHub source imports also honor `GITHUB_TOKEN` when present, which avoids
unauthenticated GitHub API rate limits while reading repository metadata.

Frontend settings:

| Variable | Purpose |
| --- | --- |
| `WARDN_HUB_API_INTERNAL_BASE_URL` | Backend URL reached by the Next.js server-side proxy. Defaults to `http://localhost:8000`. |
| `NEXT_PUBLIC_SITE_URL` | Public frontend base URL used for canonical metadata, robots.txt, sitemap URLs, and llms.txt. Defaults to `https://hub.wardnai.dev` in production and `http://localhost:3000` locally. |
| `NEXT_PUBLIC_REGISTRY_PUBLIC_BASE_URL` | Browser-visible public registry URL used for generated README badge Markdown. Defaults to `https://hub.wardnai.dev`. |
| `NEXT_PUBLIC_API_BASE_URL` | Optional browser-visible backend URL. If unset, the browser uses same-origin `/api/v1`. |
| `GOOGLE_ANALYTICS_ID` | Optional production Google Analytics measurement ID. A default ID is used in production if unset. |

Production settings reject placeholder secrets, secrets shorter than 32
characters, and wildcard CORS origins.

### OIDC Setup

Enable `oidc` in `WARDN_HUB_AUTH_PROVIDERS` and select it with
`WARDN_HUB_AUTH_DEFAULT_PROVIDER` when it should be reported as the default provider.
Configure the issuer URL, client ID, and client secret, then register this callback
with the identity provider:

```text
{WARDN_HUB_REGISTRY_PUBLIC_BASE_URL}/api/auth/oidc/callback
```

The callback is served by the frontend relay, which forwards the authorization
response to `/api/v1/auth/oidc/callback` and returns the Hub session cookie to the
browser. Override it with `WARDN_HUB_OIDC_REDIRECT_URI` only when the registered
public callback differs. The browser starts the flow through the frontend's
`/api/auth/oidc/login` relay; the backend route is `/api/v1/auth/oidc/login`.
`GET /api/v1/auth/providers` reports the enabled and default providers to the UI.
Use the normal same-origin `/api/v1` browser path for OIDC deployments so the
frontend-origin session cookie is sent on subsequent API requests.

`WARDN_HUB_OIDC_CLIENT_SECRET` and `WARDN_HUB_SESSION_SECRET` are server-side
secrets and must never be exposed through frontend environment variables. OIDC
provider tokens are exchanged by the backend; the browser receives only the
signed Hub session cookie.

OIDC sign-in requires an email claim marked with `email_verified=true`. Missing,
false, or malformed verification is rejected by default; enable
`WARDN_HUB_OIDC_ALLOW_UNVERIFIED_EMAIL` only when the provider cannot supply that
attestation. Use `WARDN_HUB_OIDC_ALLOWED_EMAIL_DOMAINS` when access must be
restricted to known domains. On first OIDC sign-in, a verified normalized email
links to an existing Hub user or creates one when auto-creation is enabled. The
stored external identity is scoped by both issuer and subject, so later sign-ins
retain the same user ID, roles, submissions, and API tokens. Treat
`WARDN_HUB_OIDC_SUPERUSER_EMAILS` as a privileged allowlist.

Hub logout clears the Hub session cookie only; it does not end the identity
provider's SSO session.

## Common Commands

From the repository root:

```sh
npm run api:openapi       # Export backend OpenAPI JSON
npm run web:api:generate  # Regenerate the frontend API client
npm run web:lint          # Lint the frontend
npm run web:build         # Build the frontend
npm run cli:check         # Type-check, test, and dry-pack the npm CLI
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

- `Tests`: backend dependency install with uv, ruff linting, pytest, CLI package
  verification, frontend npm install, frontend linting, and frontend production
  build.
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
- Enable only the intended `local` and/or `oidc` providers with
  `WARDN_HUB_AUTH_PROVIDERS`, and select one of them with
  `WARDN_HUB_AUTH_DEFAULT_PROVIDER`.
- When OIDC is enabled, configure its issuer, client ID, and backend-only client
  secret; register the HTTPS frontend relay callback derived from
  `WARDN_HUB_REGISTRY_PUBLIC_BASE_URL`.
- Review the verified-email, allowed-domain, auto-creation, and superuser-email
  policies before accepting production sign-ins.
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

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
