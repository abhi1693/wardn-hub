#!/bin/sh

set -eu

REPOSITORY="abhi1693/wardn-hub"
BRANCH="master"
SKILL_NAME="find-skills"
INSTALL_MARKER=".wardn-find-skills.json"

die() {
  echo "$*" >&2
  exit 1
}

require_commands() {
  for command_name in awk chmod curl find jq mkdir mktemp mv rm rmdir sh wc; do
    command -v "${command_name}" >/dev/null 2>&1 ||
      die "Missing required command: ${command_name}"
  done
}

download_file() {
  destination="$1"
  max_size="$2"
  url="$3"

  if ! status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 30 --max-filesize "${max_size}" \
    --output "${destination}" --write-out '%{http_code}' \
    --request GET "${url}")"; then
    return 1
  fi
  [ "${status}" = "200" ]
}

validate_skill_frontmatter() {
  awk '
    NR == 1 {
      sub(/\r$/, "")
      if ($0 != "---") exit 1
      in_frontmatter = 1
      next
    }
    in_frontmatter {
      line = $0
      sub(/\r$/, "", line)
      if (line == "---") {
        closed = 1
        in_frontmatter = 0
        next
      }
      if (line == "name: find-skills") name_count++
    }
    END {
      if (!closed || name_count != 1) exit 1
    }
  ' "$1"
}

print_result() {
  status="$1"
  revision="$2"
  directory="$3"

  jq --ascii-output --compact-output --null-input \
    --arg status "${status}" \
    --arg revision "${revision}" \
    --arg directory "${directory}" \
    '{status: $status, skill: "find-skills", revision: $revision, directory: $directory}'
}

require_commands
[ "$#" -eq 0 ] || die "Usage: AGENT_SKILLS_DIR=/absolute/path install-find-skills.sh"
: "${AGENT_SKILLS_DIR:?Set AGENT_SKILLS_DIR to the host agent's user-level skills directory}"
case "${AGENT_SKILLS_DIR}" in
  /*) ;;
  *) die "AGENT_SKILLS_DIR must be an absolute path" ;;
esac

umask 077
mkdir -p "${AGENT_SKILLS_DIR}" || die "Could not create AGENT_SKILLS_DIR"
if ! AGENT_SKILLS_DIR="$(CDPATH= cd -P "${AGENT_SKILLS_DIR}" 2>/dev/null && pwd -P)"; then
  die "Could not resolve AGENT_SKILLS_DIR"
fi
case "${AGENT_SKILLS_DIR}" in
  /|//) die "AGENT_SKILLS_DIR must not resolve to the filesystem root" ;;
esac

target_dir="${AGENT_SKILLS_DIR}/${SKILL_NAME}"
marker_path="${target_dir}/${INSTALL_MARKER}"
lock_dir="${AGENT_SKILLS_DIR}/.${SKILL_NAME}.wardn-install.lock"
stage_dir=""
backup_container=""
old_moved="false"

cleanup() {
  [ -z "${stage_dir}" ] || rm -rf "${stage_dir}"
  if [ "${old_moved}" = "true" ] &&
    [ -n "${backup_container}" ] &&
    [ ! -e "${target_dir}" ] &&
    [ ! -L "${target_dir}" ]; then
    if mv "${backup_container}/previous" "${target_dir}" 2>/dev/null; then
      old_moved="false"
    fi
  fi
  if [ "${old_moved}" = "false" ] && [ -n "${backup_container}" ]; then
    rm -rf "${backup_container}"
  fi
  rmdir "${lock_dir}" 2>/dev/null || :
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

if ! mkdir "${lock_dir}"; then
  die "Another find-skills installation or update is active"
fi

current_revision=""
if [ -e "${target_dir}" ] || [ -L "${target_dir}" ]; then
  if [ ! -d "${target_dir}" ] || [ -L "${target_dir}" ]; then
    die "find-skills target is not a regular directory: ${target_dir}"
  fi
  if [ -f "${marker_path}" ] && [ ! -L "${marker_path}" ]; then
    if ! current_revision="$(jq --exit-status --raw-output \
      --arg repository "${REPOSITORY}" '
        select(
          .schemaVersion == 1
          and .repository == $repository
          and .skill == "find-skills"
          and (.revision | type == "string" and test("^[0-9a-f]{40}$"))
        )
        | .revision
      ' "${marker_path}")"; then
      die "Installed find-skills marker failed validation: ${marker_path}"
    fi
    if [ ! -f "${target_dir}/SKILL.md" ] || [ -L "${target_dir}/SKILL.md" ] ||
      [ ! -d "${target_dir}/scripts" ] || [ -L "${target_dir}/scripts" ] ||
      [ ! -f "${target_dir}/scripts/wardn-skills.sh" ] ||
      [ -L "${target_dir}/scripts/wardn-skills.sh" ] ||
      [ ! -f "${target_dir}/scripts/install-find-skills.sh" ] ||
      [ -L "${target_dir}/scripts/install-find-skills.sh" ]; then
      die "Installed find-skills layout failed validation: ${target_dir}"
    fi
    entry_count="$(find "${target_dir}" -print | wc -l | awk '{print $1}')"
    if [ "${entry_count}" != "6" ]; then
      die "Installed find-skills directory contains unexpected files: ${target_dir}"
    fi
  else
    entry_count="$(find "${target_dir}" -print | wc -l | awk '{print $1}')"
    if [ "${entry_count}" != "4" ] ||
      [ ! -f "${target_dir}/SKILL.md" ] || [ -L "${target_dir}/SKILL.md" ] ||
      [ ! -d "${target_dir}/scripts" ] || [ -L "${target_dir}/scripts" ] ||
      [ ! -f "${target_dir}/scripts/wardn-skills.sh" ] ||
      [ -L "${target_dir}/scripts/wardn-skills.sh" ] ||
      ! validate_skill_frontmatter "${target_dir}/SKILL.md"; then
      die "Refusing to replace a find-skills directory not managed by Wardn"
    fi
  fi
fi

stage_dir="$(mktemp -d "${AGENT_SKILLS_DIR}/.${SKILL_NAME}.stage.XXXXXX")" ||
  die "Could not create a staged find-skills installation"
chmod 700 "${stage_dir}" || die "Could not secure the staged find-skills installation"

if [ -n "${WARDN_FIND_SKILLS_REVISION:-}" ]; then
  if ! revision="$(printf '%s' "${WARDN_FIND_SKILLS_REVISION}" |
    jq --exit-status --raw-input --raw-output \
      'select(test("^[0-9a-f]{40}$"))')"; then
    die "WARDN_FIND_SKILLS_REVISION must be a 40-character lowercase Git revision"
  fi
else
  if ! download_file \
    "${stage_dir}/commit.json" \
    262144 \
    "https://api.github.com/repos/${REPOSITORY}/commits/${BRANCH}"; then
    die "Could not resolve an immutable Wardn Hub revision"
  fi
  if ! revision="$(jq --exit-status --raw-output \
    '.sha | strings | select(test("^[0-9a-f]{40}$"))' \
    "${stage_dir}/commit.json")"; then
    die "Wardn Hub returned an invalid revision"
  fi
  rm -f "${stage_dir}/commit.json" || die "Could not remove staged revision metadata"
fi

if [ -n "${current_revision}" ] && [ "${current_revision}" = "${revision}" ]; then
  rm -rf "${stage_dir}"
  stage_dir=""
  print_result "unchanged" "${revision}" "${target_dir}"
else
  mkdir -p "${stage_dir}/scripts" || die "Could not create the staged skill layout"
  raw_root="https://raw.githubusercontent.com/${REPOSITORY}/${revision}/skills/find-skills"
  if ! download_file "${stage_dir}/SKILL.md" 131072 "${raw_root}/SKILL.md"; then
    die "Could not download find-skills/SKILL.md"
  fi
  if ! download_file \
    "${stage_dir}/scripts/wardn-skills.sh" \
    262144 \
    "${raw_root}/scripts/wardn-skills.sh"; then
    die "Could not download find-skills/scripts/wardn-skills.sh"
  fi
  if ! download_file \
    "${stage_dir}/scripts/install-find-skills.sh" \
    131072 \
    "${raw_root}/scripts/install-find-skills.sh"; then
    die "Could not download find-skills/scripts/install-find-skills.sh"
  fi
  validate_skill_frontmatter "${stage_dir}/SKILL.md" ||
    die "Downloaded find-skills/SKILL.md failed validation"
  sh -n "${stage_dir}/scripts/wardn-skills.sh" ||
    die "Downloaded Wardn resolver failed shell validation"
  sh -n "${stage_dir}/scripts/install-find-skills.sh" ||
    die "Downloaded find-skills installer failed shell validation"
  chmod 700 \
    "${stage_dir}/scripts/wardn-skills.sh" \
    "${stage_dir}/scripts/install-find-skills.sh" ||
    die "Could not make the find-skills scripts executable"
  if ! jq --ascii-output --null-input \
    --arg repository "${REPOSITORY}" --arg revision "${revision}" \
    '{
      schemaVersion: 1,
      repository: $repository,
      skill: "find-skills",
      revision: $revision
    }' >"${stage_dir}/${INSTALL_MARKER}"; then
    die "Could not write the find-skills installation marker"
  fi
  chmod 600 "${stage_dir}/${INSTALL_MARKER}" ||
    die "Could not secure the find-skills installation marker"

  if [ -e "${target_dir}" ] || [ -L "${target_dir}" ]; then
    backup_container="$(mktemp -d \
      "${AGENT_SKILLS_DIR}/.${SKILL_NAME}.backup.XXXXXX")" ||
      die "Could not create a find-skills backup directory"
    if ! mv "${target_dir}" "${backup_container}/previous"; then
      die "Could not stage the previous find-skills installation"
    fi
    old_moved="true"
    result_status="updated"
  else
    result_status="installed"
  fi
  if ! mv "${stage_dir}" "${target_dir}"; then
    die "Could not install find-skills"
  fi
  stage_dir=""
  if [ "${old_moved}" = "true" ]; then
    if ! rm -rf "${backup_container}"; then
      die "Could not remove the previous find-skills installation"
    fi
    backup_container=""
    old_moved="false"
  fi
  print_result "${result_status}" "${revision}" "${target_dir}"
fi

if ! rmdir "${lock_dir}"; then
  die "Could not release the find-skills installation lock"
fi
trap - HUP INT TERM
trap - 0
