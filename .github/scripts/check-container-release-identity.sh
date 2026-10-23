#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_REF_TYPE:-}" != tag ]]; then
  echo 'Container publication requires the immutable matching Hub release tag.' >&2
  exit 1
fi

version=$(python3 -c 'import tomllib; print(tomllib.load(open("hub/backend/pyproject.toml", "rb"))["project"]["version"])')
[[ "${GITHUB_REF_NAME:-}" == "v${version}" ]]
[[ "${GITHUB_REF:-}" == "refs/tags/v${version}" ]]
[[ -z "${REQUESTED_VERSION:-}" || "${REQUESTED_VERSION}" == "$version" ]]
[[ -z "${RELEASE_TAG_NAME:-}" || "${RELEASE_TAG_NAME}" == "${GITHUB_REF_NAME}" ]]
tag_commit=$(git rev-parse --verify "refs/tags/${GITHUB_REF_NAME}^{commit}")
[[ "$tag_commit" == "${GITHUB_SHA:-}" ]]
[[ "$(git rev-parse HEAD)" == "${GITHUB_SHA:-}" ]]
