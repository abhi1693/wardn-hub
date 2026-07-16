import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESOLVER = REPOSITORY_ROOT / "skills/find-skills/scripts/wardn-skills.sh"


def run_search_resolver(tmp_path: Path, response: dict) -> subprocess.CompletedProcess[str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the find-skills resolver")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift
done
cp "$WARDN_TEST_RESPONSE" "$output"
printf '200'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WARDN_TEST_RESPONSE": str(response_path),
    }
    return subprocess.run(
        ["sh", str(RESOLVER), "search", "weather"],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def search_response() -> dict:
    return {
        "query": "weather",
        "searchType": "skills",
        "count": 1,
        "durationMs": 3,
        "data": [
            {
                "id": "acme/skills/weather",
                "slug": "weather",
                "source": "acme/skills",
                "name": "Weather",
                "description": "Check the weather.",
                "isOfficial": False,
                "isDuplicate": False,
                "installs": 42,
                "url": "https://hub.wardn.ai/skills/acme/skills/weather",
                "sourceUrl": "https://github.com/acme/skills",
            }
        ],
    }


def run_audit_resolver(tmp_path: Path, response: dict) -> subprocess.CompletedProcess[str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the find-skills resolver")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift
done
cp "$WARDN_TEST_RESPONSE" "$output"
printf '200'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WARDN_TEST_RESPONSE": str(response_path),
    }
    return subprocess.run(
        ["sh", str(RESOLVER), "audit", "acme/skills/weather"],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def audit_response() -> dict:
    return {
        "id": "acme/skills/weather",
        "source": "acme/skills",
        "slug": "weather",
        "contentHash": "a" * 64,
        "audits": [
            {
                "provider": "Wardn Hub",
                "slug": "wardn-bundle-policy-v1",
                "status": "pass",
                "summary": "Bundle passed policy checks.",
                "auditedAt": "2026-07-16T12:00:00Z",
                "riskLevel": "low",
                "categories": ["bundle-policy"],
            }
        ],
    }


def test_search_resolver_returns_install_count(tmp_path: Path) -> None:
    result = run_search_resolver(tmp_path, search_response())

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["data"][0]["installs"] == 42


@pytest.mark.parametrize("installs", [None, -1, 1.5, "42"])
def test_search_resolver_rejects_invalid_install_count(
    tmp_path: Path,
    installs: object,
) -> None:
    response = search_response()
    response["data"][0]["installs"] = installs

    result = run_search_resolver(tmp_path, response)

    assert result.returncode == 1
    assert "search response failed validation" in result.stderr


def run_bundle_resolver(
    tmp_path: Path,
    *,
    disable_telemetry: bool = False,
    fail_telemetry: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the find-skills resolver")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$WARDN_TEST_CURL_LOG"
case "$*" in
  *"/skills/telemetry/"*)
    [ "${WARDN_TEST_TELEMETRY_FAIL:-}" != "1" ]
    exit
    ;;
esac
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift
done
cp "$WARDN_TEST_RESPONSE" "$output"
printf '200'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    response_path = tmp_path / "bundle.json"
    response_path.write_text(
        json.dumps(
            {
                "id": "acme/skills/weather",
                "hash": "a" * 64,
                "files": [
                    {
                        "path": "SKILL.md",
                        "contents": (
                            "---\nname: weather\n"
                            "description: Check the weather.\n---\n# Weather\n"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    curl_log = tmp_path / "curl.log"
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TMPDIR": str(bundle_root),
        "WARDN_TEST_CURL_LOG": str(curl_log),
        "WARDN_TEST_RESPONSE": str(response_path),
        "WARDN_TEST_TELEMETRY_FAIL": "1" if fail_telemetry else "",
    }
    if disable_telemetry:
        env["WARDN_HUB_DISABLE_TELEMETRY"] = "1"
    else:
        env.pop("WARDN_HUB_DISABLE_TELEMETRY", None)
        env.pop("DO_NOT_TRACK", None)
    result = subprocess.run(
        ["sh", str(RESOLVER), "fetch-bundle", "acme/skills/weather", "a" * 64],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, curl_log


def test_audit_resolver_returns_snapshot_content_hash(tmp_path: Path) -> None:
    result = run_audit_resolver(tmp_path, audit_response())

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["contentHash"] == "a" * 64
    assert output["hardRejectCount"] == 0


def test_audit_resolver_rejects_unbound_audit_response(tmp_path: Path) -> None:
    response = audit_response()
    response.pop("contentHash")

    result = run_audit_resolver(tmp_path, response)

    assert result.returncode == 1
    assert "audit response failed validation" in result.stderr


def test_bundle_resolver_reports_telemetry_after_materialization(tmp_path: Path) -> None:
    result, curl_log = run_bundle_resolver(tmp_path)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    bundle_dir = Path(manifest["directory"])
    assert (bundle_dir / "SKILL.md").is_file()
    requests = curl_log.read_text(encoding="utf-8").splitlines()
    assert len(requests) == 2
    assert "/skills/telemetry/acme/skills/weather" in requests[1]
    assert f"content_hash={'a' * 64}" in requests[1]
    assert "resolver_version=1" in requests[1]

    shutil.rmtree(bundle_dir)


def test_bundle_resolver_telemetry_can_be_disabled(tmp_path: Path) -> None:
    result, curl_log = run_bundle_resolver(tmp_path, disable_telemetry=True)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    requests = curl_log.read_text(encoding="utf-8").splitlines()
    assert len(requests) == 1
    assert "/skills/telemetry/" not in requests[0]

    shutil.rmtree(manifest["directory"])


def test_bundle_resolver_ignores_telemetry_failure(tmp_path: Path) -> None:
    result, _curl_log = run_bundle_resolver(tmp_path, fail_telemetry=True)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert Path(manifest["directory"]).is_dir()

    shutil.rmtree(manifest["directory"])
