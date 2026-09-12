#!/usr/bin/env bash
set -euo pipefail
uv run python -m app.openapi --output ../frontend/openapi/wardn-hub-api.json
git diff --exit-code -- ../frontend/openapi/wardn-hub-api.json
