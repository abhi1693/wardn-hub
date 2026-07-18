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

If `find-skills` is not installed, install it first:

```sh
npx -y @wardn-ai/skills install 'abhi1693/wardn-hub/find-skills' --global --agent codex
```

## Release Checklist

Use this checklist when asked to release Wardn Hub and related home-lab workloads.

1. Verify the Hub repo before release:
   - Run `npm run backend:lint`.
   - Run `npm run backend:test`.
   - Run `npm run web:lint`.
   - Run `npm run web:build`.
   - After changing the Hub version, run `npm run web:api:generate` before committing.
   - Commit and push Hub changes to `master`.

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
   - For scoring, prefer the configured ARM runner. If GitHub refuses the ARM runner because of billing or runner availability, build and push the `linux/arm64` scoring image from the local system instead of changing the workflow to a standard runner.

4. Confirm images before updating workloads:
   - Check the expected GHCR tags exist for Hub backend, Hub frontend, and scoring.
   - Check the `registry.home/ghcr.io/...` mirror resolves those same tags.

5. Update home-lab workloads:
   - Work in `/home/asaharan/PycharmProjects/home-lab`.
   - Update only Wardn Hub related image tags under `kubernetes/projects/applications/apps/wardn-hub`.
   - Run `kubectl kustomize kubernetes/projects/applications/apps/wardn-hub`.
   - Commit and push home-lab changes to `master`.

6. Do not restart local servers or apply Kubernetes workloads unless explicitly asked.
