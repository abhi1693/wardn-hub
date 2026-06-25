#!/bin/sh
set -eu

is_web_command() {
  if [ "$#" -eq 0 ]; then
    return 0
  fi

  if [ "$1" = "web" ]; then
    return 0
  fi

  if [ "$1" = "node" ] && [ "${2:-}" = ".next/standalone/hub/frontend/server.js" ]; then
    return 0
  fi

  return 1
}

if is_web_command "$@"; then
  ./docker-build-next.sh
  echo "Starting Wardn Hub frontend..."
  exec node .next/standalone/hub/frontend/server.js
fi

exec "$@"
