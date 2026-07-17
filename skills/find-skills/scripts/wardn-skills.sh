#!/bin/sh

set -eu

API="https://hub.wardnai.dev/api/v1"
RESOLVER_VERSION="2"
INSTALL_MARKER=".wardn-skill.json"

die() {
  echo "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
Usage:
  wardn-skills.sh search QUERY [OWNER]
  wardn-skills.sh audit SKILL_ID
  wardn-skills.sh inspect SKILL_ID
  wardn-skills.sh fetch SKILL_ID
  wardn-skills.sh fetch-chunk SKILL_ID EXPECTED_HASH OFFSET LENGTH
  wardn-skills.sh fetch-bundle SKILL_ID EXPECTED_HASH
  wardn-skills.sh install SKILL_ID EXPECTED_HASH AGENT_SKILLS_DIR
EOF
  exit 2
}

require_commands() {
  for command_name in awk base64 chmod curl jq mkdir mktemp mv rm rmdir wc; do
    command -v "${command_name}" >/dev/null 2>&1 ||
      die "Missing required command: ${command_name}"
  done
}

detect_base64_decoder() {
  if printf '' | base64 --decode >/dev/null 2>&1; then
    BASE64_DECODE_FLAG="--decode"
  elif printf '' | base64 -d >/dev/null 2>&1; then
    BASE64_DECODE_FLAG="-d"
  elif printf '' | base64 -D >/dev/null 2>&1; then
    BASE64_DECODE_FLAG="-D"
  else
    die "The installed base64 command does not provide a supported decode flag"
  fi
}

encode_skill_id() {
  jq --exit-status --null-input --raw-output --arg id "$1" '
    def valid_segment:
      length > 0
      and length <= 200
      and . != "."
      and . != ".."
      and test("^[A-Za-z0-9._-]+$");
    ($id | split("/")) as $segments
    | if ($id | length) <= 768
        and ($segments | length) >= 2
        and ($segments | length) <= 8
        and ($segments | all(valid_segment))
      then ($segments | map(@uri) | join("/"))
      else error("invalid Wardn skill ID")
      end
  '
}

record_install_telemetry() {
  encoded_id="$1"
  content_hash="$2"

  if [ -n "${WARDN_HUB_DISABLE_TELEMETRY:-}" ] || [ -n "${DO_NOT_TRACK:-}" ]; then
    return 0
  fi

  if ! curl -q --proto '=https' --silent --fail \
    --max-time 5 --max-filesize 4096 \
    --output /dev/null --request POST \
    "${API}/skills/telemetry/${encoded_id}?content_hash=${content_hash}&resolver_version=${RESOLVER_VERSION}" \
    >/dev/null 2>&1; then
    :
  fi
}

search_skills() {
  query="$1"
  owner="${2-}"
  [ -n "${query}" ] || die "Wardn skill search query cannot be empty"

  search_file=""
  cleanup_search() {
    [ -z "${search_file}" ] || rm -f "${search_file}"
  }
  trap cleanup_search 0

  search_file="$(mktemp)" || die "Could not create a temporary Wardn search file"

  if [ -n "${owner}" ]; then
    if ! http_status="$(curl -q --proto '=https' --silent --show-error \
      --max-time 15 --max-filesize 262144 \
      --output "${search_file}" --write-out '%{http_code}' \
      --get "${API}/skills/search" \
      --data-urlencode "q=${query}" \
      --data-urlencode "limit=8" \
      --data-urlencode "owner=${owner}")"; then
      die "Wardn skill search request failed"
    fi
  elif ! http_status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 15 --max-filesize 262144 \
    --output "${search_file}" --write-out '%{http_code}' \
    --get "${API}/skills/search" \
    --data-urlencode "q=${query}" \
    --data-urlencode "limit=8")"; then
    die "Wardn skill search request failed"
  fi

  [ "${http_status}" = "200" ] ||
    die "Wardn skill search returned HTTP ${http_status}"

  if ! jq --ascii-output --compact-output --exit-status '
      def valid_id:
        type == "string"
        and length <= 768
        and (split("/") | length >= 2 and length <= 8)
        and (split("/") | all(
          length > 0
          and length <= 200
          and . != "."
          and . != ".."
          and test("^[A-Za-z0-9._-]+$")
        ));
      def valid_candidate:
        type == "object"
        and (.id | valid_id)
        and (.slug | type == "string" and test("^[a-z0-9]+(?:[-_][a-z0-9]+)*$"))
        and (.source | type == "string" and length > 0 and length <= 300)
        and (.id == (.source + "/" + .slug))
        and (.name | type == "string" and length > 0 and length <= 200)
        and (.description | type == "string")
        and (.isOfficial | type == "boolean")
        and (.isDuplicate | . == null or type == "boolean")
        and (.installs | type == "number" and . >= 0 and . == floor)
        and (.url | type == "string" and length <= 2048 and test("^https://[^ \\t\\r\\n]+$"))
        and (.sourceUrl | . == null or (type == "string" and length <= 2048));
      if type == "object"
        and (.query | type == "string")
        and (.searchType | type == "string")
        and (.count | type == "number" and . >= 0)
        and (.durationMs | type == "number" and . >= 0)
        and (.data | type == "array" and all(valid_candidate))
        and (.count == (.data | length))
      then {
        query,
        count,
        data: [.data[] | {
          id,
          name,
          description: (.description[0:500]),
          source,
          isOfficial,
          isDuplicate,
          installs,
          url,
          sourceUrl
        }]
      }
      else error("invalid Wardn skill search schema")
      end
    ' "${search_file}"; then
    die "Wardn skill search response failed validation"
  fi

  rm -f "${search_file}"
  search_file=""
  trap - 0
}

audit_skill() {
  id="$1"
  if ! encoded_id="$(encode_skill_id "${id}")"; then
    die "Wardn skill ID failed validation"
  fi

  audit_file=""
  cleanup_audit() {
    [ -z "${audit_file}" ] || rm -f "${audit_file}"
  }
  trap cleanup_audit 0

  audit_file="$(mktemp)" || die "Could not create a temporary Wardn audit file"

  if ! http_status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 15 --max-filesize 131072 \
    --output "${audit_file}" --write-out '%{http_code}' \
    --request GET \
    "${API}/skills/audit/${encoded_id}")"; then
    die "Wardn skill audit request failed"
  fi

  if [ "${http_status}" = "200" ]; then
    if ! jq --ascii-output --compact-output --exit-status --arg id "${id}" '
        def nonempty_string:
          type == "string" and length > 0;
        def valid_provider_slug:
          nonempty_string
          and length <= 120
          and . != "."
          and . != ".."
          and test("^[A-Za-z0-9._-]+$");
        def audit_time_key:
          capture(
            "^(?<whole>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\\.(?<fraction>[0-9]{1,9}))?(?:Z|\\+00:00)$"
          )
          | .whole + "." + (((.fraction // "") + "000000000")[0:9]);
        def normalized_risk:
          ((.riskLevel // "")
            | gsub("^[ \\t\\r\\n]+|[ \\t\\r\\n]+$"; "")
            | ascii_downcase);
        def decision_severity:
          normalized_risk as $risk
          | if ($risk != ""
              and $risk != "low"
              and $risk != "medium"
              and $risk != "high"
              and $risk != "critical") then 2
            elif .status == "fail" or $risk == "high" or $risk == "critical" then 2
            elif .status == "warn" or $risk == "medium" then 1
            elif $risk == "" or $risk == "low" then 0
            else 2
            end;
        def latest_by_provider:
          group_by(.slug)
          | map(
            map(. + {timeKey: (.auditedAt | audit_time_key)})
            | (map(.timeKey) | max) as $latest_time
            | map(select(.timeKey == $latest_time))
            | max_by(decision_severity)
          );
        def valid_audit:
          type == "object"
          and (.provider | nonempty_string and length <= 80)
          and (.slug | valid_provider_slug)
          and (.status | . == "pass" or . == "warn" or . == "fail")
          and (.summary | type == "string")
          and (.auditedAt | type == "string" and test(
            "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?(Z|\\+00:00)$"
          ))
          and (.riskLevel | . == null or (type == "string" and length <= 32))
          and (.categories | . == null or (
            type == "array"
            and length <= 8
            and all(type == "string" and length <= 64)
          ));
        if type == "object"
          and .id == $id
          and (.contentHash | type == "string" and test("^[a-f0-9]{64}$"))
          and (.audits | type == "array" and length > 0 and length <= 32 and all(valid_audit))
          and ([.audits[].slug] | unique | length <= 8)
        then
          (.audits | latest_by_provider) as $latest
          | {
              id,
              contentHash,
              hardRejectCount: ([$latest[] | select(decision_severity == 2)] | length),
              warningCount: ([$latest[] | select(decision_severity == 1)] | length),
              failureCount: ([.audits[] | select(.status == "fail")] | length),
              latestAudits: ([$latest[] | {
                  slug,
                  provider,
                  status,
                  riskLevel,
                  auditedAt,
                  categories,
                  summary: (.summary | gsub("[\\r\\n\\t]"; " ") | .[0:240]),
                  summaryTruncated: (.summary | length > 240)
                }])
            }
        else
          error("invalid Wardn skill audit schema or identity")
        end
      ' "${audit_file}"; then
      die "Wardn skill audit response failed validation"
    fi
  elif [ "${http_status}" = "404" ]; then
    jq --ascii-output --compact-output --null-input --arg id "${id}" \
      '{id: $id, auditStatus: "unaudited"}'
  else
    die "Wardn skill audit returned HTTP ${http_status}"
  fi

  rm -f "${audit_file}"
  audit_file=""
  trap - 0
}

fetch_skill() {
  id="$1"
  mode="$2"
  expected_hash="${3-}"
  offset="${4-}"
  chunk_length="${5-}"

  if [ "${mode}" = "chunk" ]; then
    case "${offset}" in
      0) ;;
      [1-9]*)
        case "${offset}" in
          *[!0-9]*) die "Chunk offset must be a canonical non-negative integer" ;;
        esac
        ;;
      *) die "Chunk offset must be a canonical non-negative integer" ;;
    esac
    case "${chunk_length}" in
      [1-9]*)
        case "${chunk_length}" in
          *[!0-9]*) die "Chunk length must be a canonical positive integer" ;;
        esac
        ;;
      *) die "Chunk length must be a canonical positive integer" ;;
    esac
    if [ "${#offset}" -gt 5 ] || [ "${offset}" -gt 65535 ]; then
      die "Chunk offset must not exceed 65535"
    fi
    [ "${#chunk_length}" -le 4 ] ||
      die "Chunk length must be between 1 and 8000 characters"
    if [ "${chunk_length}" -lt 1 ] || [ "${chunk_length}" -gt 8000 ]; then
      die "Chunk length must be between 1 and 8000 characters"
    fi
    if ! printf '%s' "${expected_hash}" |
      jq --exit-status --raw-input 'test("^[0-9a-f]{64}$")' >/dev/null; then
      die "Expected hash must be a 64-character lowercase SHA-256 value"
    fi
  fi

  if ! encoded_id="$(encode_skill_id "${id}")"; then
    die "Wardn skill ID failed validation"
  fi

  detail_file=""
  skill_file=""
  cleanup_fetch() {
    [ -z "${detail_file}" ] || rm -f "${detail_file}"
    [ -z "${skill_file}" ] || rm -f "${skill_file}"
  }
  trap cleanup_fetch 0

  detail_file="$(mktemp)" || die "Could not create a temporary Wardn detail file"
  skill_file="$(mktemp)" || die "Could not create a temporary Wardn skill file"

  if ! http_status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 15 --max-filesize 524288 \
    --output "${detail_file}" --write-out '%{http_code}' \
    --request GET \
    "${API}/skills/${encoded_id}")"; then
    die "Wardn skill detail request failed"
  fi

  [ "${http_status}" = "200" ] ||
    die "Wardn skill detail returned HTTP ${http_status}"

  if ! jq --exit-status --arg id "${id}" '
      (.id == $id)
      and (.hash | type == "string" and test("^[0-9a-f]{64}$"))
      and (.files | type == "array" and length == 1)
      and (.files[0].path == "SKILL.md")
      and (.files[0].contents | type == "string")
      and ((.files[0] | has("encoding") | not) or .files[0].encoding == "utf-8")
      and ((.files[0] | has("executable") | not) or (.files[0].executable | type == "boolean"))
      and (.files[0].contents | length > 0 and length <= 65536)
      and (.files[0].contents | test("\\r(?!\\n)") | not)
      and (.files[0].contents | explode | all(
        . == 9
        or . == 10
        or . == 13
        or (
          . >= 32
          and (. < 127 or . > 159)
          and . != 1564
          and (. < 8206 or . > 8207)
          and (. < 8234 or . > 8238)
          and (. < 8294 or . > 8297)
        )
      ))
    ' "${detail_file}" >/dev/null; then
    die "Wardn skill detail failed validation"
  fi

  hash="$(jq --exit-status --raw-output '.hash' "${detail_file}")"
  if ! jq --exit-status --raw-output --join-output '.files[0].contents' \
    "${detail_file}" >"${skill_file}"; then
    die "Wardn SKILL.md extraction failed"
  fi

  if ! awk '
      function trim(value) {
        sub(/^[[:space:]]+/, "", value)
        sub(/[[:space:]]+$/, "", value)
        return value
      }
      function is_hex(value) {
        return value ~ /^[0-9A-Fa-f]+$/
      }
      function valid_scalar(value, first, inner, lower, position, character, closing, tail, remainder, next_character, escape_length, digits) {
        value = trim(value)
        first = substr(value, 1, 1)
        if (first == "\"" || first == "\047") {
          for (position = 2; position <= length(value); position++) {
            character = substr(value, position, 1)
            if (first == "\"" && character == "\\") {
              next_character = substr(value, position + 1, 1)
              if (next_character == "0" || next_character == "a" ||
                next_character == "b" || next_character == "t" ||
                next_character == "n" || next_character == "v" ||
                next_character == "f" || next_character == "r" ||
                next_character == "e" || next_character == " " ||
                next_character == "\"" || next_character == "/" ||
                next_character == "\\" || next_character == "N" ||
                next_character == "_" || next_character == "L" ||
                next_character == "P") {
                position++
                continue
              }
              if (next_character == "x") escape_length = 2
              else if (next_character == "u") escape_length = 4
              else if (next_character == "U") escape_length = 8
              else return 0
              digits = substr(value, position + 2, escape_length)
              if (length(digits) != escape_length || !is_hex(digits)) return 0
              position += escape_length + 1
              continue
            }
            if (first == "\047" && character == first) {
              next_character = substr(value, position + 1, 1)
              if (next_character == first) {
                position++
                continue
              }
            }
            if (character == first) {
              closing = position
              break
            }
          }
          if (!closing) return 0
          tail = substr(value, closing + 1)
          remainder = trim(tail)
          if (remainder != "" && tail !~ /^[[:space:]]+#/) return 0
          inner = trim(substr(value, 2, closing - 2))
          return inner != ""
        }

        position = match(value, /(^|[[:space:]])#/)
        if (position) value = trim(substr(value, 1, position - 1))
        lower = tolower(value)
        if (value == "" || value == "~" || value ~ /^[>|][+-]?$/) return 0
        if (value == "-" || value == ":") return 0
        if (lower ~ /^(null|true|false|yes|no|on|off)$/) return 0
        if (value ~ /^-?[0-9]+([.][0-9]+)?$/) return 0
        first = substr(value, 1, 1)
        if (first == "!" || first == "&" || first == "*" ||
          first == "[" || first == "{" || first == "?" ||
          first == "@" || first == "`" || first == "%" ||
          first == "]" || first == "}" || first == "," ||
          first == "|" || first == ">") return 0
        if (first == "-" && value ~ /^-[[:space:]]/) return 0
        if (value ~ /:[[:space:]]/) return 0
        return 1
      }
      NR == 1 {
        sub(/\r$/, "")
        if ($0 != "---") exit 1
        frontmatter = 1
        next
      }
      frontmatter {
        line = $0
        sub(/\r$/, "", line)
        if (line == "---") {
          closed = 1
          frontmatter = 0
          next
        }
        if (description_block) {
          if (line == "") next
          if (line ~ /^[[:space:]]/) {
            if (trim(line) != "") description_valid = 1
            next
          }
          if (line ~ /^#/) next
          description_block = 0
        }
        if (line ~ /^name:/) {
          name_count++
          value = line
          sub(/^name:/, "", value)
          if (valid_scalar(value)) name_valid = 1
        }
        if (line ~ /^description:/) {
          description_count++
          value = line
          sub(/^description:/, "", value)
          value = trim(value)
          if (value ~ /^[>|][+-]?([[:space:]]+#.*)?$/) {
            description_block = 1
          } else if (valid_scalar(value)) {
            description_valid = 1
          }
        }
      }
      closed && $0 ~ /[^[:space:]]/ {
        body = 1
      }
      END {
        if (!(closed &&
          name_count == 1 &&
          description_count == 1 &&
          name_valid &&
          description_valid &&
          body)) exit 1
      }
    ' "${skill_file}"; then
    die "Wardn SKILL.md frontmatter or body failed validation"
  fi

  characters="$(jq --exit-status --raw-output '.files[0].contents | length' \
    "${detail_file}")"

  case "${mode}" in
    inspect)
      printf 'Wardn skill id=%s hash=%s characters=%s\n' \
        "${id}" "${hash}" "${characters}"
      ;;
    full)
      printf 'Wardn skill id=%s hash=%s characters=%s\n' \
        "${id}" "${hash}" "${characters}"
      cat "${skill_file}"
      ;;
    chunk)
      [ "${hash}" = "${expected_hash}" ] ||
        die "Wardn skill hash changed since inspection"
      [ "${offset}" -lt "${characters}" ] ||
        die "Chunk offset is beyond the Wardn skill content"
      end=$((offset + chunk_length))
      if [ "${end}" -gt "${characters}" ]; then
        end="${characters}"
      fi
      jq --ascii-output --compact-output --exit-status \
        --arg id "${id}" \
        --arg hash "${hash}" \
        --argjson offset "${offset}" \
        --argjson end "${end}" \
        --argjson characters "${characters}" \
        '{
          id: $id,
          hash: $hash,
          offset: $offset,
          end: $end,
          characters: $characters,
          content: .files[0].contents[$offset:$end]
        }' \
        "${detail_file}"
      ;;
    *)
      die "Unknown Wardn fetch mode"
      ;;
  esac
}

fetch_bundle() {
  id="$1"
  expected_hash="$2"

  if ! printf '%s' "${expected_hash}" |
    jq --exit-status --raw-input 'test("^[0-9a-f]{64}$")' >/dev/null; then
    die "Expected hash must be a 64-character lowercase SHA-256 value"
  fi
  if ! encoded_id="$(encode_skill_id "${id}")"; then
    die "Wardn skill ID failed validation"
  fi

  detect_base64_decoder
  umask 077
  bundle_file=""
  records_file=""
  bundle_dir=""
  bundle_complete="false"
  cleanup_bundle() {
    [ -z "${bundle_file}" ] || rm -f "${bundle_file}"
    [ -z "${records_file}" ] || rm -f "${records_file}"
    if [ "${bundle_complete}" != "true" ] && [ -n "${bundle_dir}" ]; then
      rm -rf "${bundle_dir}"
    fi
  }
  trap cleanup_bundle 0

  bundle_file="$(mktemp)" || die "Could not create a temporary Wardn bundle file"
  records_file="$(mktemp)" || die "Could not create a temporary Wardn bundle records file"

  if ! http_status="$(curl -q --proto '=https' --silent --show-error \
    --max-time 60 --max-filesize 50331648 \
    --output "${bundle_file}" --write-out '%{http_code}' \
    --get "${API}/skills/${encoded_id}" \
    --data-urlencode 'include_bundle=true')"; then
    die "Wardn skill bundle request failed"
  fi

  [ "${http_status}" = "200" ] ||
    die "Wardn skill bundle returned HTTP ${http_status}"

  if ! jq --exit-status --arg id "${id}" --arg hash "${expected_hash}" '
      def safe_codepoint:
        . == 9
        or . == 10
        or . == 13
        or (
          . >= 32
          and (. < 127 or . > 159)
          and . != 1564
          and (. < 8206 or . > 8207)
          and (. < 8234 or . > 8238)
          and (. < 8294 or . > 8297)
        );
      def valid_path:
        type == "string"
        and length > 0
        and length <= 1024
        and (startswith("/") | not)
        and (contains("\\") | not)
        and (explode | all(
          . >= 32
          and (. < 127 or . > 159)
          and . != 1564
          and (. < 8206 or . > 8207)
          and (. < 8234 or . > 8238)
          and (. < 8294 or . > 8297)
        ))
        and (
          split("/")
          | length <= 64
          and all(length > 0 and length <= 255 and . != "." and . != "..")
        );
      def valid_text:
        type == "string"
        and length <= 8388608
        and (explode | all(safe_codepoint));
      def valid_base64:
        type == "string"
        and length <= 11184812
        and (length % 4 == 0)
        and test("^[A-Za-z0-9+/]*={0,2}$");
      def valid_file:
        type == "object"
        and (.path | valid_path)
        and (.contents | type == "string")
        and ((.encoding // "utf-8") == "utf-8" or .encoding == "base64")
        and ((.executable // false) | type == "boolean")
        and (
          if (.encoding // "utf-8") == "utf-8"
          then (.contents | valid_text)
          else (.contents | valid_base64)
          end
        );
      (.id == $id)
      and (.hash == $hash)
      and (.files | type == "array" and length > 0 and length <= 256)
      and (.files | all(valid_file))
      and (([.files[].path] | unique | length) == (.files | length))
      and ([.files[] | select(.path == "SKILL.md")] | length == 1)
      and (
        .files[]
        | select(.path == "SKILL.md")
        | (.encoding // "utf-8") == "utf-8"
          and (.contents | length > 0 and length <= 65536)
          and (.contents | test("\\r(?!\\n)") | not)
      )
    ' "${bundle_file}" >/dev/null; then
    die "Wardn skill bundle failed validation or changed since inspection"
  fi

  if ! jq --compact-output --exit-status '.files[]' \
    "${bundle_file}" >"${records_file}"; then
    die "Wardn skill bundle records could not be extracted"
  fi

  temp_root="${TMPDIR:-/tmp}"
  case "${temp_root}" in
    /*) ;;
    *) temp_root="/tmp" ;;
  esac
  bundle_dir="$(mktemp -d "${temp_root%/}/wardn-skill.XXXXXX")" ||
    die "Could not create a private Wardn bundle directory"
  chmod 700 "${bundle_dir}" || die "Could not secure the Wardn bundle directory"

  total_bytes=0
  while IFS= read -r record; do
    path="$(printf '%s' "${record}" | jq --exit-status --raw-output '.path')" ||
      die "Wardn skill bundle path extraction failed"
    encoding="$(printf '%s' "${record}" |
      jq --exit-status --raw-output '.encoding // "utf-8"')" ||
      die "Wardn skill bundle encoding extraction failed"
    executable="$(printf '%s' "${record}" |
      jq --exit-status --raw-output '
        (.executable // false) | if . then "true" else "false" end
      ')" ||
      die "Wardn skill bundle mode extraction failed"

    case "${path}" in
      */*)
        parent="${path%/*}"
        mkdir -p "${bundle_dir}/${parent}" ||
          die "Could not create a Wardn skill bundle subdirectory"
        ;;
    esac
    output_file="${bundle_dir}/${path}"
    if [ "${encoding}" = "utf-8" ]; then
      if ! printf '%s' "${record}" |
        jq --exit-status --join-output --raw-output '.contents' >"${output_file}"; then
        die "Could not write a Wardn UTF-8 bundle file"
      fi
    elif ! printf '%s' "${record}" |
      jq --exit-status --raw-output '.contents' |
      base64 "${BASE64_DECODE_FLAG}" >"${output_file}"; then
      die "Could not decode a Wardn base64 bundle file"
    fi

    file_bytes="$(wc -c <"${output_file}" | awk '{print $1}')"
    [ "${file_bytes}" -le 8388608 ] ||
      die "Wardn skill bundle file exceeds 8388608 bytes"
    total_bytes=$((total_bytes + file_bytes))
    [ "${total_bytes}" -le 16777216 ] ||
      die "Wardn skill bundle exceeds 16777216 decoded bytes"

    if [ "${executable}" = "true" ]; then
      chmod 700 "${output_file}" || die "Could not set Wardn bundle file permissions"
    else
      chmod 600 "${output_file}" || die "Could not set Wardn bundle file permissions"
    fi
  done <"${records_file}"

  if ! jq --ascii-output --compact-output --exit-status \
    --arg directory "${bundle_dir}" \
    --argjson bytes "${total_bytes}" '
      {
        id,
        hash,
        directory: $directory,
        fileCount: (.files | length),
        decodedBytes: $bytes,
        files: [.files[] | {
          path,
          encoding: (.encoding // "utf-8"),
          executable: (.executable // false)
        }]
      }
    ' "${bundle_file}"; then
    die "Could not summarize the Wardn skill bundle"
  fi

  rm -f "${bundle_file}" "${records_file}"
  bundle_file=""
  records_file=""
  bundle_complete="true"
  record_install_telemetry "${encoded_id}" "${expected_hash}"
  trap - 0
}

print_install_result() {
  status="$1"
  id="$2"
  content_hash="$3"
  directory="$4"

  jq --ascii-output --compact-output --null-input \
    --arg status "${status}" \
    --arg id "${id}" \
    --arg hash "${content_hash}" \
    --arg directory "${directory}" \
    '{status: $status, id: $id, hash: $hash, directory: $directory}'
}

install_bundle() {
  id="$1"
  expected_hash="$2"
  agent_skills_dir="$3"

  if ! printf '%s' "${expected_hash}" |
    jq --exit-status --raw-input 'test("^[0-9a-f]{64}$")' >/dev/null; then
    die "Expected hash must be a 64-character lowercase SHA-256 value"
  fi
  if ! encode_skill_id "${id}" >/dev/null; then
    die "Wardn skill ID failed validation"
  fi
  case "${agent_skills_dir}" in
    /*) ;;
    *) die "Agent skills directory must be an absolute path" ;;
  esac

  umask 077
  mkdir -p "${agent_skills_dir}" ||
    die "Could not create the agent skills directory"
  if ! agent_skills_dir="$(CDPATH= cd -P "${agent_skills_dir}" 2>/dev/null && pwd -P)"; then
    die "Could not resolve the agent skills directory"
  fi
  case "${agent_skills_dir}" in
    /|//) die "Agent skills directory must not resolve to the filesystem root" ;;
  esac

  slug="${id##*/}"
  target_dir="${agent_skills_dir}/${slug}"
  marker_path="${target_dir}/${INSTALL_MARKER}"
  lock_dir="${agent_skills_dir}/.${slug}.wardn-install.lock"
  manifest_file=""
  bundle_dir=""
  backup_container=""
  old_moved="false"

  cleanup_install() {
    [ -z "${manifest_file}" ] || rm -f "${manifest_file}"
    [ -z "${bundle_dir}" ] || rm -rf "${bundle_dir}"
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
  trap cleanup_install 0
  trap 'exit 1' HUP INT TERM

  if ! mkdir "${lock_dir}"; then
    die "Another Wardn skill installation is active for ${slug}"
  fi

  current_hash=""
  if [ -e "${target_dir}" ] || [ -L "${target_dir}" ]; then
    if [ ! -d "${target_dir}" ] || [ -L "${target_dir}" ]; then
      die "Skill target is not a regular directory: ${target_dir}"
    fi
    if [ ! -f "${marker_path}" ] || [ -L "${marker_path}" ]; then
      die "Refusing to replace a skill not managed by Wardn: ${target_dir}"
    fi
    if ! current_hash="$(jq --exit-status --raw-output --arg id "${id}" '
        select(
          .schemaVersion == 1
          and .id == $id
          and (.contentHash | type == "string" and test("^[0-9a-f]{64}$"))
        )
        | .contentHash
      ' "${marker_path}")"; then
      die "Installed Wardn skill marker failed validation: ${marker_path}"
    fi
  fi

  manifest_file="$(mktemp "${agent_skills_dir}/.${slug}.manifest.XXXXXX")" ||
    die "Could not create a Wardn installation manifest"
  if ! (
    TMPDIR="${agent_skills_dir}"
    export TMPDIR
    fetch_bundle "${id}" "${expected_hash}"
  ) >"${manifest_file}"; then
    die "Could not fetch the complete Wardn skill bundle"
  fi

  if ! bundle_dir="$(jq --exit-status --raw-output \
      --arg id "${id}" --arg hash "${expected_hash}" '
        select(.id == $id and .hash == $hash)
        | .directory
        | select(type == "string" and length > 0)
      ' "${manifest_file}")"; then
    die "Wardn installation manifest failed validation"
  fi
  case "${bundle_dir}" in
    "${agent_skills_dir}"/wardn-skill.*) ;;
    *)
      bundle_dir=""
      die "Wardn bundle directory escaped the agent skills directory"
      ;;
  esac
  if [ ! -d "${bundle_dir}" ] || [ -L "${bundle_dir}" ]; then
    bundle_dir=""
    die "Wardn bundle directory failed validation"
  fi
  if [ -e "${bundle_dir}/${INSTALL_MARKER}" ] ||
    [ -L "${bundle_dir}/${INSTALL_MARKER}" ]; then
    die "Wardn bundle contains the reserved installation marker"
  fi
  if ! jq --ascii-output --null-input \
    --arg id "${id}" --arg content_hash "${expected_hash}" \
    '{schemaVersion: 1, id: $id, contentHash: $content_hash}' \
    >"${bundle_dir}/${INSTALL_MARKER}"; then
    die "Could not write the Wardn installation marker"
  fi
  chmod 600 "${bundle_dir}/${INSTALL_MARKER}" ||
    die "Could not secure the Wardn installation marker"

  if [ -n "${current_hash}" ] && [ "${current_hash}" = "${expected_hash}" ]; then
    rm -rf "${bundle_dir}"
    bundle_dir=""
    print_install_result "unchanged" "${id}" "${expected_hash}" "${target_dir}"
  elif [ -n "${current_hash}" ]; then
    backup_container="$(mktemp -d "${agent_skills_dir}/.${slug}.backup.XXXXXX")" ||
      die "Could not create a Wardn skill backup directory"
    if ! mv "${target_dir}" "${backup_container}/previous"; then
      die "Could not stage the previous Wardn skill installation"
    fi
    old_moved="true"
    if ! mv "${bundle_dir}" "${target_dir}"; then
      die "Could not update the Wardn skill installation"
    fi
    bundle_dir=""
    if ! rm -rf "${backup_container}"; then
      die "Could not remove the previous Wardn skill installation"
    fi
    backup_container=""
    old_moved="false"
    print_install_result "updated" "${id}" "${expected_hash}" "${target_dir}"
  else
    if [ -e "${target_dir}" ] || [ -L "${target_dir}" ]; then
      die "Skill target appeared during installation: ${target_dir}"
    fi
    if ! mv "${bundle_dir}" "${target_dir}"; then
      die "Could not install the Wardn skill"
    fi
    bundle_dir=""
    print_install_result "installed" "${id}" "${expected_hash}" "${target_dir}"
  fi

  rm -f "${manifest_file}"
  manifest_file=""
  if ! rmdir "${lock_dir}"; then
    die "Could not release the Wardn skill installation lock"
  fi
  trap - HUP INT TERM
  trap - 0
}

require_commands

case "${1-}" in
  search)
    if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
      usage
    fi
    search_skills "$2" "${3-}"
    ;;
  audit)
    [ "$#" -eq 2 ] || usage
    audit_skill "$2"
    ;;
  inspect)
    [ "$#" -eq 2 ] || usage
    fetch_skill "$2" inspect
    ;;
  fetch)
    [ "$#" -eq 2 ] || usage
    fetch_skill "$2" full
    ;;
  fetch-chunk)
    [ "$#" -eq 5 ] || usage
    fetch_skill "$2" chunk "$3" "$4" "$5"
    ;;
  fetch-bundle)
    [ "$#" -eq 3 ] || usage
    fetch_bundle "$2" "$3"
    ;;
  install)
    [ "$#" -eq 4 ] || usage
    install_bundle "$2" "$3" "$4"
    ;;
  *)
    usage
    ;;
esac
