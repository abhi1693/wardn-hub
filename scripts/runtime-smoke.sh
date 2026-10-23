#!/bin/sh
# Shared container-images.yml interface: image, native platform, app version.
set -eu
exec python3 "$(dirname "$0")/runtime_smoke.py" "$@"
