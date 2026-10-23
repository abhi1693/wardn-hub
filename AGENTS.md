# Wardn Hub Agent Notes

Wardn Hub is the registry and submission product for MCP server definitions. It is
not a runtime product.

Keep runtime concerns out of this repo unless the implementation plan changes:

- Do not add workspace MCP installs.
- Do not add MCP tool invocation routes.
- Do not add Kubernetes runtime management.
- Do not add a gateway execution plane.

The intended layout follows the Wardn AI monorepo shape:

- Backend: `hub/backend`
- Frontend: `hub/frontend`
- API prefix: `/api/v1`
- Settings prefix: `WARDN_HUB_`

## Skill Discovery

For every substantive task in this repo, search Wardn Hub for applicable skills
using the `find-skills` skill before proceeding. If an applicable Wardn Hub skill
is found, use it according to the `find-skills` workflow.

- Do not run `npx @wardn-ai/skills` directly from this repo. The npm workspace
  shadows the published package with the local `hub/cli`, which may expect an
  unreleased Hub API schema.
- Run every Wardn CLI discovery command through a neutral npm prefix so npm uses
  the published package while the CLI keeps this repo as its working directory:

```sh
npm exec --yes --prefix /tmp --package=@wardn-ai/skills -- \
  wardn-skills search "QUERY" --limit 8 --json
```

- Use the same `npm exec ... -- wardn-skills` prefix for `audit`, `inspect`,
  `fetch-bundle`, and other `find-skills` workflow commands.

If `find-skills` is not installed, install it first:

```sh
npm exec --yes --prefix /tmp --package=@wardn-ai/skills -- \
  wardn-skills install 'abhi1693/wardn-hub/find-skills' --global --agent codex
```

## Release Checklist

Use this checklist when asked to release Wardn Hub and related home-lab workloads.
Source-preparation and pull-request tasks stop before publication or deployment
unless those actions are explicitly authorized.

1. Verify the Hub repo before release:
   - Run `npm run backend:lint`.
   - Run `npm run backend:test`.
   - Run `npm run web:lint`.
   - Run `npm run web:build`.
   - After changing the Hub version, run `npm run web:api:generate` before committing.
   - Require the source pull request and native image checks to pass before the
     authorized merge to `master`.

2. Verify the scoring app when the change depends on scoring behavior:
   - Work in `/home/asaharan/PycharmProjects/wardn-hub-scoring`.
   - Run `uv run ruff check .`.
   - Run `uv run pytest`.
   - Bump the scoring app version when releasing a new scoring image.
   - Commit and push scoring changes to `master`.

3. Publish releases:
   - Create the next Hub GitHub release tag, for example `v0.2.x`.
   - Create the next scoring GitHub release tag, for example `v0.1.x`, when scoring changed.
   - Watch the container image workflow for Hub until it succeeds.
   - Use the available hosted native runners declared by the shared image
     manifest. Missing runners or failed checks block publication. Repair the
     permanent workflow through a reviewed source change; do not publish from a
     local system or introduce a temporary runner fallback.
   - Preserve existing immutable release tags and images. If released source
     needs a repair, prepare the next patch version rather than moving its tag.
   - Publish `@wardn-ai/skills` independently using its own package version and
     matching `skills-vVERSION` tag, after verifying compatibility with the live
     Hub API. Its version is not the Hub or scoring application version.

4. Confirm images before updating workloads:
   - Verify Hub backend, frontend, and Codex app-server as one application-version
     cohort, including native ARM64 availability and immutable digests. Scoring
     retains its independently released version.
   - Require strict scans including unfixed HIGH/CRITICAL findings, SBOMs, native
     application smoke and release/source-version parity before promotion. Keep
     signed GitHub artifact attestations enabled for this public Hub repository;
     a private component's explicit capability setting does not apply here.
   - Check the `registry.home/ghcr.io/...` mirror resolves the verified digests.

5. Update home-lab workloads:
   - Work in `/home/asaharan/PycharmProjects/home-lab`.
   - Update all 14 Hub cohort image occurrences atomically under
     `kubernetes/projects/applications/apps/wardn-hub`, including backend init
     containers and paused worker/Codex deployments. Preserve paused replicas.
   - Coordinate the frontend image with its dedicated `docker-build-next.sh`
     command and consistent builder/restore/cleanup cache-key version. Do not
     combine a new image runtime contract with the previous builder command.
   - Update scoring's main image only to its separately verified release.
   - Run `kubectl kustomize kubernetes/projects/applications/apps/wardn-hub`.
   - Commit and push home-lab changes to `master`.

6. Do not restart local servers or apply Kubernetes workloads unless explicitly asked.
