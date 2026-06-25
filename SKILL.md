---
name: wardn-hub-server-submission
description: Use this skill when preparing a Wardn Hub MCP server submission from a source repository, README, existing server.json/mcp.json, or package metadata, including new server and new version submissions.
---

# Wardn Hub Server Submission

Use this skill to turn a source MCP server project into a complete Wardn Hub submission. Wardn Hub is a registry and submission product, not a runtime. Do not add runtime installs, MCP tool invocation routes, Kubernetes management, or gateway execution-plane details.

## Submission Flow

- Create a draft submission with `POST /api/v1/submissions`.
- Submit the draft for review with `POST /api/v1/submissions/{id}/submit`.
- **New server**: use `submissionType: "new_server"` and version `1.0.0`.
- **New version**: use `submissionType: "new_version"`, keep the existing `name`, and set the new semver.

Use only this submission flow. Do not prepare direct admin-publish payloads.

## Source Inspection

Always inspect the source before building the payload. Prefer local files. If only a repository URL is provided, fetch or browse the repository contents before drafting the submission.

Read these files when present:

- `README.md`, `README.*`, or docs landing page.
- Existing `server.json`, `mcp.json`, `.mcp/server.json`, or package-provided MCP metadata.
- Package manifests: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `deno.json`, `uv.lock`, lockfiles, or release metadata.
- Documentation files under `docs/`, especially setup, authentication, tools, resources, prompts, transport, examples, and deployment pages.
- License, changelog, and release notes when they clarify version, stability, or compatibility.

Use `rg --files` to discover files quickly. Read the README first, then manifests, then focused docs. Do not rely on package names or repository names alone when README/docs contain better product wording.

## Extract Details From README And Source

Build a short evidence-backed summary before writing JSON:

- **Identity**: project name, display title, publisher/namespace, repository URL, website/docs URL.
- **Purpose**: what the server does, which domain it serves, and who it is for.
- **Capabilities**: tools, resources, prompts, major operations, supported services/APIs.
- **Install target**: package manager, package name, binary/entrypoint, command, version, runtime requirements.
- **Remote target**: HTTP/SSE/WebSocket endpoint, transport type, auth requirements, docs URL.
- **Configuration**: env vars, headers, command arguments, required secrets, optional settings, scopes/permissions.
- **Authentication**: OAuth/API key/personal token/service account flow, required external permissions, rate limits.
- **Compatibility**: MCP schema/version, supported platforms, Node/Python/etc. versions, known limitations.
- **Trust metadata**: license, maintainer, organization, support URL, issue tracker, security policy.
- **Categories**: infer from documented purpose, not from vague keywords.

If a detail is absent, leave it empty or omit it if the schema allows. Do not invent endpoints, tools, categories, credentials, or support claims.

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
- Runtime command or binary when documented.
- Required environment variables, marking secret values as secret metadata.
- Command arguments and supported transports when documented.

If the source includes install examples such as `npx`, `uvx`, `pipx`, `docker run`, or `go install`, translate them into package metadata rather than prose only.

## Remote Metadata Guidance

Use `remotes` for hosted MCP endpoints. Preserve:

- URL.
- Transport type, such as streamable HTTP, SSE, WebSocket, or stdio-over-remote proxy if explicitly documented.
- Authentication mechanism.
- Required headers, marking secret values as secret metadata.
- Public docs/support URL.

Do not create a remote entry for a local stdio server unless the source documents an actual hosted endpoint.

## Documentation Field

The `documentation` field should be useful in the catalog without requiring the reader to open the source repo. Build it from the README and docs with these sections when information exists:

```markdown
## Overview

## Capabilities

## Installation

## Configuration

## Authentication

## Example Usage

## Limitations

## Support
```

Keep it factual. Paraphrase source docs rather than copying long passages. Include exact env var names, package names, commands, and URLs when they are necessary for use.

## Submission Payload

Use this shape for `POST /api/v1/submissions`:

```json
{
  "submissionType": "new_server",
  "ownerUserId": null,
  "ownerOrganizationId": null,
  "serverJson": {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "name": "publisher/server",
    "title": "Server Display Name",
    "description": "Short source-backed description of the MCP server.",
    "documentation": "Markdown documentation synthesized from source README and docs.",
    "repository": {
      "type": "git",
      "url": "https://github.com/example/server"
    },
    "version": "1.0.0",
    "websiteUrl": "https://example.com/docs",
    "icons": [],
    "packages": [],
    "remotes": [],
    "_meta": {
      "categories": [],
      "source": {
        "readme": "README.md",
        "repository": "https://github.com/example/server"
      }
    }
  }
}
```

For a new version, change `submissionType` to `new_version`, keep the same `name`, and set `version` to the new semver.

After creating the draft, submit it:

```sh
curl -X POST "$WARDN_HUB_API_BASE_URL/submissions/$SUBMISSION_ID/submit" \
  -H "Authorization: Bearer $WARDN_HUB_API_TOKEN"
```

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
- `name` is stable `publisher/server` and matches the required pattern.
- `version` is semver; new servers use `1.0.0`.
- `description` is source-backed and non-empty.
- `documentation` includes setup and usage details from the README/docs.
- At least one of `packages` or `remotes` is non-empty.
- Package/remotes metadata matches source install or endpoint documentation.
- URLs are valid HTTP(S) URLs where required.
- Secrets are represented only as required variable/header names, never plaintext values.
- `_meta.categories` are inferred from documented behavior.
- The payload uses API prefix `/api/v1`.
