#!/usr/bin/env bash
set -euo pipefail
npm --workspace hub/frontend run api:generate
npm run cli:check
