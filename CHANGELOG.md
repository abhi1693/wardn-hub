# Changelog

## 0.2.182 (release preparation)

- Update all runtime, development and optional package manifests and regenerate
  their transitive lockfiles from current package registries.
- Upgrade Next.js and its tooling together to 16.4.2, React to 19.3.1 and the
  supported build/runtime Node.js line to 26.12.1.
- Keep ESLint at 9.39.5 because the current React, import and accessibility plugins
  do not support ESLint 10. Keep TypeScript at 6.0.3 because typescript-eslint
  requires TypeScript below 6.1. These are explicit compatibility limits.
- Reuse the tested, licensed local braces depth fix for CVE-2026-93687 until an
  upstream fixed release exists; include dependency security regression tests.

This change prepares the next patch release. Tags, releases, image publication
and deployment require the subsequent release workflow.

The independently versioned `@wardn-ai/skills` CLI is prepared as 0.1.9 because
its runtime YAML parser and compiler/type dependencies change in this update.

Upgrade Cisco AI Skill Scanner to 2.3.1 and keep its installed-version assertion
and audit configuration hash synchronized. Existing persisted 2.0.12 audits
become stale under the new scanner configuration and require the normal re-audit
workflow after a separately authorized release. Adopt Typer's public Exit type
and remove the Redis SDK's deleted proxy setting; application middleware still
passes its explicit client identifier and preserves its configured rate limits.
The CLI can use TypeScript 7.0.2 independently; the frontend retains the lint
peer-compatible TypeScript 6.0.3.

Remove obsolete global js-yaml/nanoid overrides so each consumer resolves the
newest patched version within its own compatible API range. Refresh the retained
PostCSS, Sharp and Hono security overrides within their existing major lines.
The Python resolver retains protobuf 6 and python-dateutil 2 where the current
OpenTelemetry and AWS SDK dependency ranges exclude newer major versions.

Declare the C++/atomic runtime libraries explicitly in the backend image that
copies the Node 26 executable from the official Node image.

Pin the backend to the current official Python 3.13.17 Bookworm patch image.
