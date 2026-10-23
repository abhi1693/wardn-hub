# Repository automation

Common CI and image mechanics are maintained in [abhi1693/actions](https://github.com/abhi1693/actions).
Workflows use the released `@v1` reference for centrally maintained compatible updates.
See the [shared release history](https://github.com/abhi1693/actions/releases) for changes.
Repository-owned scripts, triggers, scanner exceptions and application smoke checks
remain alongside the application. Image manifests declare components rather than
copying workflow steps.

Pull requests build all three manifest components on native ARM64 runners with
`publish: false`. The shared workflow records SBOMs and blocks HIGH/CRITICAL
runtime findings, including unfixed findings. The same manifest, version-file
parity, scans and `scripts/runtime-smoke.sh` run before release image promotion.
The caller grants the reusable workflow's declared permission ceiling; PR builds
skip registry login, push, attestations and promotion. No production credentials
are passed to the repository-owned smoke checks.

Container publication requires the exact `vVERSION` Git tag matching
`hub/backend/pyproject.toml`. Published releases and manual dispatches must run
on that tag, with the checked-out HEAD, resolved tag commit and `GITHUB_SHA`
identical. Manual runs from moving branches fail before any image build.
The stdlib-only `.github/tests` exercise the real preflight against disposable
local Git histories; CI runs them on pull requests and master pushes. Public
Hub publication retains signed GitHub artifact attestations.

Runtime checks use disposable containers with networking disabled and generated
synthetic configuration. They exercise backend health/OpenAPI and native scanner
imports and real CEL helper evaluation, the frontend's actual build/HTTP/assets/Sharp/Faro behavior, and an
authenticated Codex app-server initialization with no turn or tool requests.
Failed synthetic runtime logs join the private image-report artifact. The app
version comes from `hub/backend/pyproject.toml`; tool versions and distrusted CA
fingerprints live in `scripts/runtime-policy.json`.
Frontend smoke also executes Fleet's GNU tar archive/restore flags on disposable
files with whitespace/newline names, dotfiles and a symlink. It verifies bytes,
ownership and safe restored permissions; BusyBox tar cannot satisfy this runtime
contract.

The only secret classification is the exact upstream public Cisco scanner test
constant in `trivy-secret.yaml`. There are no path/rule-family exclusions.
Backend smoke verifies the pinned vendor policy bytes and runs real Trivy
negative controls so different credentials continue to block publication.

The exact public fixture rule uses ASCII hexadecimal regex escapes, verified
against the upstream value and digest. This preserves the precise match without
storing a credential-shaped literal in source; push protection stays enabled.
