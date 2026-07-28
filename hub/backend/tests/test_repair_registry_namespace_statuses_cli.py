from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.cli import repair_registry_namespace_statuses as cli


def server_and_version(
    *,
    method: str = "official_registry",
    metadata_status: str = "verified",
    stored_status: str = "verified",
):
    version_id = uuid4()
    server = SimpleNamespace(
        current_version_id=version_id,
        registry_namespace_verification_status=stored_status,
    )
    version = SimpleNamespace(
        id=version_id,
        name="net.agentutil/context-mcp",
        version="1.0.0",
        registry_namespace_verification_status=stored_status,
        is_latest=True,
        server_json={
            "name": "net.agentutil/context-mcp",
            "_meta": {
                "registryNamespace": {
                    "namespace": "net.agentutil",
                    "type": "domain",
                    "authority": "agentutil.net",
                    "verificationStatus": metadata_status,
                    "verificationMethod": method,
                    "evidenceUrl": "https://registry.modelcontextprotocol.io/v0.1/servers",
                    "source": "modelcontextprotocol-registry",
                },
                "categories": ["developer-tools"],
            },
        },
    )
    return server, version


def test_repair_server_version_marks_official_registry_namespace_as_imported() -> None:
    server, version = server_and_version()

    result = cli.repair_server_version(server, version, write=True)

    assert result.status == "updated"
    assert version.registry_namespace_verification_status == "imported"
    assert server.registry_namespace_verification_status == "imported"
    namespace = version.server_json["_meta"]["registryNamespace"]
    assert namespace["verificationStatus"] == "imported"
    assert namespace["verificationMethod"] == "official_registry"
    assert version.server_json["_meta"]["categories"] == ["developer-tools"]


def test_repair_server_version_dry_run_does_not_mutate_record() -> None:
    server, version = server_and_version()

    result = cli.repair_server_version(server, version, write=False)

    assert result.status == "updated"
    assert version.registry_namespace_verification_status == "verified"
    assert server.registry_namespace_verification_status == "verified"
    assert (
        version.server_json["_meta"]["registryNamespace"]["verificationStatus"]
        == "verified"
    )


def test_repair_server_version_leaves_non_official_registry_verification() -> None:
    server, version = server_and_version(method="dns_txt")

    result = cli.repair_server_version(server, version, write=True)

    assert result.status == "unchanged"
    assert version.registry_namespace_verification_status == "verified"
    assert server.registry_namespace_verification_status == "verified"
    assert (
        version.server_json["_meta"]["registryNamespace"]["verificationStatus"]
        == "verified"
    )


def test_repair_server_version_leaves_imported_status_unchanged() -> None:
    server, version = server_and_version(
        metadata_status="imported",
        stored_status="imported",
    )

    result = cli.repair_server_version(server, version, write=True)

    assert result.status == "unchanged"
    assert version.registry_namespace_verification_status == "imported"
    assert server.registry_namespace_verification_status == "imported"
