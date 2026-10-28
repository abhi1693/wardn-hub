# Changelog

## 0.2.183 — 2026-10-28

- Remove retired Faro browser monitoring and private source-map collection.
- Patch runtime HTTP-client dependencies and avoid the affected SQLite file-lock implementation.

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

Pin the application runtime to the current official CPython 3.13.17 prefix.

Require native ARM64 runtime smoke, release-version parity, SBOMs and strict
runtime scans for all three images on pull requests and publication. Align the
Codex app-server build argument with its 0.163.0 runtime. Install backend package
metadata so its API reports the release version. Move the frontend to pinned
Node 26.12.1 Alpine, replace its global npm build dependency with the dedicated
Next/Faro entrypoint, and explicitly trace the workspace's hoisted dependencies.
These checks remain blocking if a compatible runtime image has unfixed findings.

Use the maintained Ubuntu 26.04 LTS GNU runtime for backend and Codex app-server,
with official Python 3.13.17/Node 26.12.1 prefixes and signed Ubuntu libraries.
Exclude unused GUI/installers and the base's unused unowned service manager;
preserve non-GUI native modules and require their runtime linking/TLS checks.

Build the locked Cisco scanner 2.3.1 CEL helper from its verified upstream source
with pinned Go 1.27.3 and automatic toolchain downloads disabled. Keep the SDK
out of the runtime; require native true/false CEL evaluation and invalid-input
rejection alongside scanner, ONNX and API checks.

Classify only the verified upstream scanner public test constant, retaining
all vulnerability checks and secret-rule families. Pin policy bytes and require
real secret-scanner negative controls in the native backend smoke.

Require an immutable matching `vVERSION` tag and exact tag/HEAD/workflow-source
commit equality before release or manual container publication. Add real local
Git-history regression cases, and replace the retired local-publisher fallback
with durable hosted-native workflow repair and an atomic Hub runtime cohort.

Include GNU tar in the frontend runtime for Fleet's NUL-delimited build-cache
archive and restore contract. Exercise the exact flags with unusual filenames,
dotfiles, symlinks, byte comparisons and safe ownership/permission checks in the
native PR and release image smoke.
