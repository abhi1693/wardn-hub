---
name: wardn-hub-server-submission
description: Use this skill when preparing a Wardn Hub MCP server submission from a source repository, README, existing server.json/mcp.json, or package metadata, including new server and new version submissions.
---

# Wardn Hub Server Submission

Use this skill to turn a source MCP server project into a complete Wardn Hub submission. Wardn Hub is a registry and submission product, not a runtime. Do not add runtime installs, MCP tool invocation routes, Kubernetes management, or gateway execution-plane details.

## Submission Flow

- Import source metadata with `POST /api/v1/imports/server-source`.
- Create a draft submission with `POST /api/v1/submissions`.
- Submit the draft for review with `POST /api/v1/submissions/{id}/submit`.
- **New server**: use `submissionType: "new_server"` and version `1.0.0`.
- **New version**: use `submissionType: "new_version"`, keep the existing `name`, and set the new semver.

Use only this submission flow. Do not prepare direct admin-publish payloads.

## Import First

Before reading the source manually, call the import API with the repository source. The request requires an authenticated Wardn Hub user or API token with `submissions:write`. Use the OpenAPI schema at `/api/v1/openapi.json` as the source of truth for the exact request fields, response fields, validation constraints, and examples for `POST /api/v1/imports/server-source`.

The import API fetches repository metadata, README content, and supported `server.json`/`mcp.json` metadata when available. It returns:

- `serverJson`: the system-generated registry document draft.
- `submissionPayload`: a ready-to-edit `POST /api/v1/submissions` payload.
- `evidence.files`: source files the system used.
- `evidence.missing`: required or important fields the system could not infer.

Use `submissionPayload` as the starting point. Do not rebuild the submission from scratch unless the import response is unusable.

Only read the source README/docs after import to fill in missing or weak details, especially when `evidence.missing` contains required fields such as `packages or remotes`, or when documentation, configuration, authentication, tools, resources, prompts, or limitations are incomplete. Preserve all correct fields returned by the import API.

Import is not a substitute for README/source review. Treat import output as a draft that may miss launch arguments, environment variables, optional modes, prerequisites, and tool lists. Never submit directly from import output without performing the configuration extraction pass below.

## Source Inspection

Inspect only the source areas needed to improve the import draft. Prefer local files. If only a repository URL is provided, fetch or browse the repository contents after calling the import API.

Read these files when present:

- `README.md`, `README.*`, or docs landing page.
- Existing `server.json`, `mcp.json`, `.mcp/server.json`, or package-provided MCP metadata.
- Package manifests: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `deno.json`, `uv.lock`, lockfiles, MCPB `manifest.json`, or release metadata.
- Documentation files under `docs/`, especially setup, authentication, tools, resources, prompts, transport, examples, and deployment pages.
- License, changelog, and release notes when they clarify version, stability, or compatibility.

Use `rg --files` to discover files quickly when local source is available. Read the README first, then manifests, then focused docs. Do not rely on package names or repository names alone when README/docs contain better product wording.

## Mandatory Configuration Extraction Pass

After import and README inspection, explicitly search the README/docs/manifests for these strings and sections before editing `submissionPayload`:

- `mcpServers`, `command`, `args`, `env`, `environment`, `Environment Variables`, `.env`, `API_KEY`, `TOKEN`, `SECRET`, `URL`, `HOST`, `PORT`.
- `stdio`, `streamable`, `http`, `sse`, `websocket`, `transport`, `remote`, `tunnel`, `ngrok`.
- `CLI Options`, `options`, `flags`, `arguments`, `configuration`, `prerequisites`, `requirements`.
- Manifest or package fields such as `bin`, `scripts`, `exports`, `mcp`, `server`, `runtime`, `engines`, and MCPB user configuration.

For every documented client configuration snippet or launch command, extract:

- Runtime command, for example `npx`, `uvx`, `python`, `node`, `docker`, or the installed binary name.
- Full argument list in order. Preserve flags like `--stdio`, `--read-only`, `--port`, `--host`, package names, module paths, and `-y`.
- Transport type. For local desktop client snippets, this is usually `stdio`. For local HTTP mode, record the HTTP transport only when the source says it is an MCP transport.
- Environment variables, including required and optional variables, defaults, allowed values, and whether values are secrets.
- External prerequisites, for example required desktop apps, browser extensions, plugins, local services, databases, cloud accounts, or OAuth setup.
- Safety and mode flags, for example read-only mode, host allowlists, origin allowlists, tunnel URLs, API versions, timeouts, and media/file restrictions.

Missing command arguments or environment variables is a submission-quality bug. If the README shows them, they must appear in both `serverJson.packages[].transport` or `serverJson.remotes[]` where the schema supports them and in the `documentation` field.

## Extract Details From README And Source

Build a short evidence-backed summary before editing `submissionPayload`:

- **Identity**: project name, display title, publisher/namespace, repository URL, website/docs URL.
- **Purpose**: what the server does, which domain it serves, and who it is for.
- **Capabilities**: tools, resources, prompts, major operations, supported services/APIs.
- **Install target**: package manager, package name, binary/entrypoint, command, version, runtime requirements.
- **Remote target**: HTTP/SSE/WebSocket endpoint, transport type, auth requirements, docs URL.
- **Configuration**: exact env var names, headers, command arguments, CLI flags, required secrets, optional settings, scopes/permissions, defaults, and allowed values.
- **Authentication**: OAuth/API key/personal token/service account flow, required external permissions, rate limits.
- **Compatibility**: MCP schema/version, supported platforms, Node/Python/etc. versions, known limitations.
- **Trust metadata**: license, maintainer, organization, support URL, issue tracker, security policy.
- **Categories**: infer from documented purpose, not from vague keywords.
- **Prerequisites**: local apps, plugins, APIs, services, ports, accounts, or setup steps required before the MCP server works.

If a detail is absent, leave it empty or omit it if the schema allows. Do not invent endpoints, tools, categories, credentials, or support claims.

Merge manual findings into the import API draft instead of starting from scratch. Treat `evidence.missing` as the highest-priority checklist.

## Map Source Details To `serverJson`

Required fields:

- `$schema`: use `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` unless the source declares a newer compatible schema.
- `name`: stable `publisher/server` identifier matching `^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$`.
- `version`: semver. New server submissions must use `1.0.0`.
- `description`: concise non-empty summary from README/docs.
- At least one of `packages` or `remotes` must be non-empty.

Recommended fields:

- `title`: human-readable display name, max 100 characters.
- `documentation`: Markdown synthesized from README/docs. Include setup, configuration, authentication, capabilities, examples, and limitations.
- `repository`: include `type`, `url`, branch/tag, directory, or source package metadata when known.
- `websiteUrl`: public docs/product URL.
- `icons`: only include real icon URLs or package icons found in source metadata.
- `_meta`: include categories, source evidence notes, package metadata, and review hints.
- `ownerUserId` or `ownerOrganizationId`: include only when the requester provides a known owner ID.

## Package Metadata Guidance

Use `packages` for servers installed/run locally by a client. Include only fields supported or clearly implied by source metadata. Common details to preserve:

- Registry type, such as npm, PyPI, Cargo, Go, Docker, MCPB, or another package source.
- Package identifier/name.
- Package version.
- Runtime command or binary when documented. Put it in `packages[].transport.command`.
- Command arguments exactly as documented. Put them in `packages[].transport.args` as an ordered array.
- Required and optional environment variables. Put names and source-backed defaults/placeholders in `packages[].transport.env`.
- Supported transports when documented. Put the primary local client transport in `packages[].transport.type`.
- Runtime requirements such as Node/Python versions and required local services in `documentation` and `_meta` when useful for review.

If the source includes install examples such as `npx`, `uvx`, `pipx`, `docker run`, or `go install`, translate them into package metadata rather than prose only.

For client configuration snippets, map fields directly:

```json
{
  "command": "npx",
  "args": ["-y", "@scope/server", "--stdio"],
  "env": {
    "SERVICE_URL": "http://localhost:1234",
    "SERVICE_API_KEY": "${SERVICE_API_KEY}"
  }
}
```

Use documented default values for non-secret settings. Use `${ENV_VAR_NAME}` placeholders for secrets or user-specific values. Do not put real secret values in the payload. If a variable is optional but useful, include it in documentation even when it is not placed in `transport.env`.

If the source documents several launch modes, capture the best default local MCP client mode in `packages[].transport` and describe the alternatives in `documentation`. Add separate package entries only when the package identifiers or package types differ materially, such as npm plus Docker plus MCPB.

## Remote Metadata Guidance

Use `remotes` for hosted MCP endpoints. Preserve:

- URL.
- Transport type, such as streamable HTTP, SSE, WebSocket, or stdio-over-remote proxy if explicitly documented.
- Authentication mechanism.
- Required headers, marking secret values as secret metadata.
- Public docs/support URL.

Do not create a remote entry for a local stdio server, localhost HTTP server, user-started tunnel, or ngrok URL unless the source documents a stable hosted endpoint that users can connect to directly. Local HTTP, tunnel, and ngrok modes belong in package transport metadata and documentation, not `remotes`, unless the endpoint is operated by the server publisher as a permanent service.

## Documentation Field

The `documentation` field should be useful in the catalog without requiring the reader to open the source repo. Build it from the README and docs with these sections when information exists:

```markdown
## Overview

## Capabilities

## Installation

## Configuration

## Prerequisites

## Authentication

## Example Usage

## Limitations

## Support
```

Keep it factual. Paraphrase source docs rather than copying long passages. Include exact env var names, package names, commands, and URLs when they are necessary for use.

The `Configuration` or `Installation` sections must include:

- The recommended client configuration or launch command.
- Required command arguments and their purpose.
- Required environment variables, defaults, and which values are secrets.
- Optional environment variables that materially change behavior.
- Local prerequisites and setup order.
- Remote/tunnel setup only when documented by the source.

## Submission Payload

Start from the import API's `submissionPayload`. If constructing a payload manually is unavoidable, consult `/api/v1/openapi.json` for the `SubmissionCreate` schema, required fields, nested `serverJson` model, validation constraints, and canonical examples for `POST /api/v1/submissions`.

For a new version, change `submissionType` to `new_version`, keep the same `name`, and set `version` to the new semver.

After creating the draft, submit it with `POST /api/v1/submissions/{id}/submit`.

## Missing Information Rules

Ask for missing required details only after source inspection. Ask specifically for:

- Desired `publisher/server` name if it is not obvious.
- Whether this is `new_server` or `new_version`.
- The target version when creating a new version.
- Package or remote details when neither can be extracted.
- Owner user/organization ID only if ownership assignment is needed.

Do not block on optional metadata. Submit a complete-but-honest payload with empty arrays/strings where allowed.

## Validation Checklist

Before submitting:

- Source README/docs were read and used.
- Import API output was used as the initial draft.
- README/docs/manifests were searched for `mcpServers`, `args`, `env`, environment variable tables, CLI options, and transport sections.
- `name` is stable `publisher/server` and matches the required pattern.
- `version` is semver; new servers use `1.0.0`.
- `description` is source-backed and non-empty.
- `documentation` includes setup and usage details from the README/docs.
- At least one of `packages` or `remotes` is non-empty.
- Package/remotes metadata matches source install or endpoint documentation.
- `packages[].transport.command`, `packages[].transport.args`, and `packages[].transport.env` preserve documented client configuration snippets where present.
- Required env vars and important optional env vars are listed in documentation, with defaults/placeholders and no plaintext secrets.
- CLI flags and arguments that select transport or safety mode are preserved, for example `--stdio`, `--read-only`, `--port`, `--host`, or equivalent source-specific flags.
- Local prerequisites and external service dependencies are documented.
- URLs are valid HTTP(S) URLs where required.
- Secrets are represented only as required variable/header names, never plaintext values.
- `_meta.categories` are inferred from documented behavior.
- The payload uses API prefix `/api/v1`.
