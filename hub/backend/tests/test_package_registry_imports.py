from app.modules.imports.package_registry import (
    PACKAGE_REGISTRY_EVIDENCE_META_KEY,
    add_package_registry_evidence,
    package_api_url,
)


def test_pypi_adapter_records_exact_published_version_and_runtime_metadata() -> None:
    requested_urls: list[str] = []

    def fetch_json(url: str) -> dict:
        requested_urls.append(url)
        return {
            "info": {
                "version": "2.0.2",
                "summary": "Google Search Console MCP server",
                "license": "MIT",
                "requires_python": ">=3.12",
                "requires_dist": ["mcp>=1.0"],
                "project_urls": {
                    "Source": "https://github.com/acme/search-console-mcp",
                    "Documentation": "https://example.com/docs",
                },
                "package_url": (
                    "https://pypi.org/project/mcp-google-search-console/2.0.2/"
                ),
            },
            "urls": [
                {
                    "upload_time_iso_8601": "2026-07-01T10:00:00Z",
                    "digests": {"sha256": "abc123"},
                }
            ],
        }

    result = add_package_registry_evidence(
        {
            "packages": [
                {
                    "registryType": "pypi",
                    "identifier": "mcp-google-search-console",
                    "version": "2.0.2",
                }
            ]
        },
        fetch_json=fetch_json,
    )

    assert requested_urls == [
        "https://pypi.org/pypi/mcp-google-search-console/2.0.2/json"
    ]
    evidence = result["_meta"][PACKAGE_REGISTRY_EVIDENCE_META_KEY][0]
    assert evidence["status"] == "published"
    assert evidence["resolvedVersion"] == "2.0.2"
    assert evidence["requiresPython"] == ">=3.12"
    assert evidence["dependencies"] == ["mcp>=1.0"]
    assert evidence["repository"] == "https://github.com/acme/search-console-mcp"
    assert evidence["sha256"] == "abc123"
    assert evidence["authoritativeFor"] == ["identifier", "version", "publication"]
    assert "summary" in evidence["contextOnly"]


def test_npm_adapter_encodes_scoped_package_and_records_binary() -> None:
    requested_urls: list[str] = []

    def fetch_json(url: str) -> dict:
        requested_urls.append(url)
        return {
            "name": "@acme/weather-mcp",
            "version": "1.4.0",
            "description": "Weather tools",
            "license": "Apache-2.0",
            "repository": {"url": "git+https://github.com/acme/weather-mcp.git"},
            "engines": {"node": ">=20"},
            "bin": {"weather-mcp": "dist/index.js"},
            "dist": {"integrity": "sha512-example", "shasum": "def456"},
        }

    result = add_package_registry_evidence(
        {
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@acme/weather-mcp",
                    "version": "1.4.0",
                }
            ]
        },
        fetch_json=fetch_json,
    )

    assert requested_urls == [
        "https://registry.npmjs.org/@acme%2Fweather-mcp/1.4.0"
    ]
    evidence = result["_meta"][PACKAGE_REGISTRY_EVIDENCE_META_KEY][0]
    assert evidence["status"] == "published"
    assert evidence["binaries"] == {"weather-mcp": "dist/index.js"}
    assert evidence["engines"] == {"node": ">=20"}
    assert evidence["repository"] == "https://github.com/acme/weather-mcp"


def test_registry_adapter_records_not_found_without_trusting_documentation() -> None:
    result = add_package_registry_evidence(
        {
            "documentation": "Claims version 9.9.9 exists.",
            "packages": [
                {
                    "registryType": "pypi",
                    "identifier": "weather-mcp",
                    "version": "9.9.9",
                }
            ],
        },
        fetch_json=lambda _url: {},
    )

    evidence = result["_meta"][PACKAGE_REGISTRY_EVIDENCE_META_KEY][0]
    assert evidence["status"] == "not_found"
    assert evidence["requestedVersion"] == "9.9.9"
    assert evidence["resolvedVersion"] == ""


def test_pypi_adapter_accepts_nullable_release_arrays() -> None:
    result = add_package_registry_evidence(
        {
            "packages": [
                {
                    "registryType": "pypi",
                    "identifier": "weather-mcp",
                    "version": "1.0.0",
                }
            ]
        },
        fetch_json=lambda _url: {
            "info": {
                "version": "1.0.0",
                "requires_dist": None,
            },
            "urls": None,
        },
    )

    evidence = result["_meta"][PACKAGE_REGISTRY_EVIDENCE_META_KEY][0]
    assert evidence["status"] == "published"
    assert evidence["dependencies"] == []
    assert evidence["publishedAt"] == ""
    assert evidence["sha256"] == ""


def test_package_api_url_uses_latest_when_version_is_missing() -> None:
    assert (
        package_api_url("npm", "weather-mcp", "")
        == "https://registry.npmjs.org/weather-mcp/latest"
    )
    assert (
        package_api_url("pypi", "weather-mcp", "")
        == "https://pypi.org/pypi/weather-mcp/json"
    )
