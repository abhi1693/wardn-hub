from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.cli import refresh_registry_readmes as cli


def server_and_version(
    *,
    documentation: str = "old docs",
    repository: dict | None = None,
):
    version_id = uuid4()
    server = SimpleNamespace(
        current_version_id=version_id,
        documentation=documentation,
        repository=repository,
        website_url="",
    )
    version = SimpleNamespace(
        id=version_id,
        name="io.github.example/weather",
        version="1.0.0",
        description="Weather tools.",
        documentation=documentation,
        repository=repository,
        website_url="",
        packages=[
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "transport": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@example/weather"],
                },
            }
        ],
        remotes=[],
        is_latest=True,
        server_json={
            "name": "io.github.example/weather",
            "version": "1.0.0",
            "description": "Weather tools.",
            "documentation": documentation,
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather",
                    "transport": {"type": "stdio"},
                }
            ],
            "_meta": {
                "sourceReview": {
                    "llm": {
                        "filesRead": ["README.md", "server.json"],
                    }
                }
            },
        },
    )
    return server, version


def test_refresh_server_version_prefers_readme_and_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, version = server_and_version(
        repository={"url": "https://github.com/example/weather"}
    )
    monkeypatch.setattr(cli, "fetch_readme_for_version", lambda _server, _version: "# README")

    result = cli.refresh_server_version(server, version, write=True)

    assert result.status == "updated"
    assert result.source == "readme"
    assert version.documentation == "# README"
    assert server.documentation == "# README"
    assert version.server_json["documentation"] == "# README"
    assert version.server_json["_meta"]["sourceReview"]["llm"]["filesRead"] == [
        "README.md",
        "server.json",
    ]
    assert version.server_json["packages"][0]["transport"] == {"type": "stdio"}


def test_refresh_server_version_uses_generated_fallback_when_readme_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, version = server_and_version()
    monkeypatch.setattr(cli, "fetch_readme_for_version", lambda _server, _version: "")

    result = cli.refresh_server_version(server, version, write=True)

    assert result.status == "updated"
    assert result.source == "generated"
    assert version.documentation.startswith("## Installation")
    assert "Package launch commands: npx -y @example/weather" in version.documentation
    assert version.server_json["_meta"]["sourceReview"]["llm"]["filesRead"] == [
        "README.md",
        "server.json",
    ]


def test_refresh_server_version_does_not_generate_fallback_after_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, version = server_and_version()

    def fail_fetch(_server, _version) -> str:
        raise cli.ReadmeFetchError("GitHub rate limited")

    monkeypatch.setattr(cli, "fetch_readme_for_version", fail_fetch)

    result = cli.refresh_server_version(server, version, write=True)

    assert result.status == "failed"
    assert result.source == "readme"
    assert result.reason == "GitHub rate limited"
    assert version.documentation == "old docs"
    assert version.server_json["documentation"] == "old docs"


def test_github_readme_sources_deduplicates_repository_candidates() -> None:
    server, version = server_and_version(
        repository={
            "url": "https://github.com/example/weather/tree/main/packages/mcp",
            "subfolder": "packages/mcp",
        }
    )
    version.website_url = "https://github.com/example/weather"

    assert cli.github_readme_sources(server, version) == [
        (
            "https://github.com/example/weather/tree/main/packages/mcp",
            "packages/mcp",
        ),
        ("https://github.com/example/weather", ""),
    ]
