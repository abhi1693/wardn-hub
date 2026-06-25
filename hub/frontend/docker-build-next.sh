#!/bin/sh
set -eu

standalone_root=".next/standalone"
standalone_app="$standalone_root/hub/frontend"

echo "Building Wardn Hub frontend with runtime environment..."
npm run build

rm -rf "$standalone_app/public" "$standalone_app/.next/static"
mkdir -p "$standalone_app/.next"

if [ -d public ]; then
  cp -R public "$standalone_app/public"
fi

cp -R .next/static "$standalone_app/.next/static"

echo "Wardn Hub frontend build is ready."
