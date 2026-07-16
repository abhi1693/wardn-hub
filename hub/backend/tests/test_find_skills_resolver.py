import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESOLVER = REPOSITORY_ROOT / "skills/find-skills/scripts/wardn-skills.sh"


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
