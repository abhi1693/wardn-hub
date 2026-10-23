#!/bin/sh
set -eu

standalone_root=".next/standalone"
standalone_app="$standalone_root/hub/frontend"

echo "Building Wardn Hub frontend with runtime environment..."
# Keep the package's build sequence without shipping a global package manager.
# Resolve the locked Next installation relative to this app, including hoisting.
node "$(node -p 'require.resolve("next/dist/bin/next")')" build
node scripts/prepare-faro-sourcemaps.mjs

rm -rf "$standalone_app/public" "$standalone_app/.next/static"
mkdir -p "$standalone_app/.next"

if [ -d public ]; then
  cp -R public "$standalone_app/public"
fi

cp -R .next/static "$standalone_app/.next/static"

echo "Wardn Hub frontend build is ready."
