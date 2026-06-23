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

