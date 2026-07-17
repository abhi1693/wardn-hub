import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESOLVER = REPOSITORY_ROOT / "skills/find-skills/scripts/wardn-skills.sh"
FIND_SKILLS_INSTALLER = (
    REPOSITORY_ROOT / "skills/find-skills/scripts/install-find-skills.sh"
)


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
    assert "resolver_version=2" in requests[1]

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


def run_install_resolver(
    tmp_path: Path,
    agent_skills_dir: Path,
    content_hash: str,
    *,
    skill_body: str = "# Weather\n",
    extra_files: list[dict[str, object]] | None = None,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the find-skills resolver")
    bin_dir = tmp_path / "install-bin"
    bin_dir.mkdir(exist_ok=True)
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
case "$*" in
  *"/skills/telemetry/"*) exit 0 ;;
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
    files: list[dict[str, object]] = [
        {
            "path": "SKILL.md",
            "contents": (
                "---\nname: weather\ndescription: Check the weather.\n---\n" + skill_body
            ),
        },
        {
            "path": "references/forecast.md",
            "contents": "Forecast reference.\n",
        },
    ]
    files.extend(extra_files or [])
    response_path = tmp_path / "install-response.json"
    response_path.write_text(
        json.dumps(
            {
                "id": "acme/skills/weather",
                "hash": content_hash,
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WARDN_TEST_RESPONSE": str(response_path),
        "WARDN_HUB_DISABLE_TELEMETRY": "1",
    }
    return subprocess.run(
        [
            "sh",
            str(RESOLVER),
            "install",
            "acme/skills/weather",
            content_hash,
            str(agent_skills_dir),
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_resolver_persists_and_updates_a_validated_bundle(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"
    first_hash = "a" * 64
    second_hash = "b" * 64

    installed = run_install_resolver(
        tmp_path,
        agent_skills_dir,
        first_hash,
        skill_body="# Weather v1\n",
    )

    assert installed.returncode == 0, installed.stderr
    assert json.loads(installed.stdout)["status"] == "installed"
    target = agent_skills_dir / "weather"
    assert (target / "references/forecast.md").read_text(encoding="utf-8") == (
        "Forecast reference.\n"
    )
    assert json.loads((target / ".wardn-skill.json").read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "id": "acme/skills/weather",
        "contentHash": first_hash,
    }

    unchanged = run_install_resolver(tmp_path, agent_skills_dir, first_hash)

    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout)["status"] == "unchanged"

    updated = run_install_resolver(
        tmp_path,
        agent_skills_dir,
        second_hash,
        skill_body="# Weather v2\n",
    )

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert "# Weather v2" in (target / "SKILL.md").read_text(encoding="utf-8")
    marker = json.loads((target / ".wardn-skill.json").read_text(encoding="utf-8"))
    assert marker["contentHash"] == second_hash
    assert not list(agent_skills_dir.glob(".weather.*"))
    assert not list(agent_skills_dir.glob("wardn-skill.*"))


def test_install_resolver_refuses_to_replace_an_unmanaged_skill(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"
    target = agent_skills_dir / "weather"
    target.mkdir(parents=True)
    existing = target / "SKILL.md"
    existing.write_text("user-owned\n", encoding="utf-8")

    result = run_install_resolver(tmp_path, agent_skills_dir, "a" * 64)

    assert result.returncode == 1
    assert "not managed by Wardn" in result.stderr
    assert existing.read_text(encoding="utf-8") == "user-owned\n"


def test_install_resolver_rejects_reserved_marker_from_bundle(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"

    result = run_install_resolver(
        tmp_path,
        agent_skills_dir,
        "a" * 64,
        extra_files=[{"path": ".wardn-skill.json", "contents": "{}\n"}],
    )

    assert result.returncode == 1
    assert "reserved installation marker" in result.stderr
    assert not (agent_skills_dir / "weather").exists()
    assert not list(agent_skills_dir.glob("wardn-skill.*"))


def run_find_skills_installer(
    tmp_path: Path,
    agent_skills_dir: Path,
    revision: str,
    *,
    pin_revision: bool = False,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the find-skills installer")
    bin_dir = tmp_path / "self-install-bin"
    bin_dir.mkdir(exist_ok=True)
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
output=
url=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  else
    url="$1"
  fi
  shift
done
case "$url" in
  *"api.github.com/"*) cp "$WARDN_TEST_COMMIT" "$output" ;;
  *"/SKILL.md") cp "$WARDN_TEST_SKILL" "$output" ;;
  *"/wardn-skills.sh") cp "$WARDN_TEST_RESOLVER" "$output" ;;
  *"/install-find-skills.sh") cp "$WARDN_TEST_INSTALLER" "$output" ;;
  *) exit 1 ;;
esac
printf '200'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    commit_path = tmp_path / "commit.json"
    commit_path.write_text(json.dumps({"sha": revision}), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AGENT_SKILLS_DIR": str(agent_skills_dir),
        "WARDN_FIND_SKILLS_REVISION": revision if pin_revision else "",
        "WARDN_TEST_COMMIT": str(commit_path),
        "WARDN_TEST_SKILL": str(REPOSITORY_ROOT / "skills/find-skills/SKILL.md"),
        "WARDN_TEST_RESOLVER": str(RESOLVER),
        "WARDN_TEST_INSTALLER": str(FIND_SKILLS_INSTALLER),
    }
    return subprocess.run(
        ["sh", str(FIND_SKILLS_INSTALLER)],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_find_skills_installer_supports_install_check_and_update(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"
    first_revision = "a" * 40
    second_revision = "b" * 40

    installed = run_find_skills_installer(
        tmp_path,
        agent_skills_dir,
        first_revision,
        pin_revision=True,
    )

    assert installed.returncode == 0, installed.stderr
    assert json.loads(installed.stdout)["status"] == "installed"
    target = agent_skills_dir / "find-skills"
    assert (target / "scripts/wardn-skills.sh").is_file()
    assert (target / "scripts/install-find-skills.sh").is_file()
    marker_path = target / ".wardn-find-skills.json"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["revision"] == first_revision

    unchanged = run_find_skills_installer(tmp_path, agent_skills_dir, first_revision)

    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout)["status"] == "unchanged"

    updated = run_find_skills_installer(tmp_path, agent_skills_dir, second_revision)

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["revision"] == second_revision
    assert not list(agent_skills_dir.glob(".find-skills.*"))


def test_find_skills_installer_upgrades_the_legacy_layout(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"
    target = agent_skills_dir / "find-skills"
    scripts_dir = target / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(REPOSITORY_ROOT / "skills/find-skills/SKILL.md", target / "SKILL.md")
    shutil.copy(RESOLVER, scripts_dir / "wardn-skills.sh")

    result = run_find_skills_installer(tmp_path, agent_skills_dir, "c" * 40)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "updated"
    assert (target / ".wardn-find-skills.json").is_file()
    assert (scripts_dir / "install-find-skills.sh").is_file()


def test_find_skills_installer_refuses_an_unmanaged_directory(tmp_path: Path) -> None:
    agent_skills_dir = tmp_path / "agent-skills"
    target = agent_skills_dir / "find-skills"
    target.mkdir(parents=True)
    existing = target / "notes.txt"
    existing.write_text("keep me\n", encoding="utf-8")

    result = run_find_skills_installer(tmp_path, agent_skills_dir, "d" * 40)

    assert result.returncode == 1
    assert "not managed by Wardn" in result.stderr
    assert existing.read_text(encoding="utf-8") == "keep me\n"
