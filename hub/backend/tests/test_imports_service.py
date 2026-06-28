from app.modules.imports import service
from app.modules.imports.schemas import ServerSourceImportRequest


def test_import_server_source_uses_server_json(monkeypatch) -> None:
    def fetch_json(url: str):
        return {
            "name": "weather-mcp",
            "description": "Weather server",
            "homepage": "https://weather.example.com",
            "html_url": "https://github.com/acme/weather-mcp",
            "owner": {"avatar_url": "https://github.com/acme.png"},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        if "/readme" in url:
            return "# Weather MCP\n\nWeather forecast tools."
        if "server.json" in url and "/main/" in url:
            return """
            {
              "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
              "name": "io.github.acme/weather-mcp",
              "description": "Weather forecast MCP tools.",
              "version": "1.0.0",
              "packages": [
                {
                  "registry_type": "npm",
                  "registry_base_url": "https://registry.npmjs.org",
                  "identifier": "@acme/weather-mcp",
                  "environment_variables": [
                    {
                      "name": "WEATHER_API_TOKEN",
                      "description": "Weather API token.",
                      "is_required": true,
                      "is_secret": true,
                      "format": "string"
                    }
                  ]
                }
              ],
              "_meta": {"categories": ["weather"]}
            }
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(repositoryUrl="https://github.com/acme/weather-mcp"),
    )

    assert response.source == "server.json"
    assert response.server_json.name == "io.github.acme/weather-mcp"
    assert response.server_json.documentation == "# Weather MCP\n\nWeather forecast tools."
    assert response.server_json.packages[0].registry_type == "npm"
    assert response.server_json.packages[0].registry_base_url == "https://registry.npmjs.org"
    assert response.server_json.packages[0].identifier == "@acme/weather-mcp"
    assert response.server_json.packages[0].environment_variables[0].name == "WEATHER_API_TOKEN"
    assert response.server_json.packages[0].environment_variables[0].is_required is True
    serialized = response.server_json.model_dump(by_alias=True, exclude_none=True)
    assert serialized["packages"][0]["registryType"] == "npm"
    assert serialized["packages"][0]["registryBaseUrl"] == "https://registry.npmjs.org"
    assert serialized["packages"][0]["environmentVariables"][0]["isSecret"] is True
    assert response.server_json.meta is not None
    assert response.server_json.meta["categories"] == ["weather"]
    assert response.server_json.meta["sourceReview"]["llm"]["filesRead"] == [
        "README.md",
        "server.json",
    ]
    assert response.submission_payload.server_json == response.server_json
    assert response.evidence.files == ["README.md", "server.json"]
    assert response.evidence.missing == [
        "package transport command",
        "package transport args",
    ]


def test_import_server_source_returns_readme_fallback_when_metadata_missing(monkeypatch) -> None:
    def fetch_json(url: str):
        return {
            "name": "weather-mcp",
            "description": "Weather server",
            "html_url": "https://github.com/acme/weather-mcp",
            "owner": {},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        if "/readme" in url:
            return "# Weather MCP\n\nWeather forecast tools."
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(repositoryUrl="acme/weather-mcp"),
    )

    assert response.source == "github"
    assert response.title == "weather-mcp"
    assert response.server_json.documentation == "# Weather MCP\n\nWeather forecast tools."
    assert response.server_json.meta is not None
    assert response.server_json.meta["sourceReview"]["llm"]["filesRead"] == ["README.md"]
    assert response.evidence.missing == ["packages or remotes"]


def test_import_server_source_derives_subfolder_from_github_tree_url(monkeypatch) -> None:
    fetched_urls: list[str] = []

    def fetch_json(url: str):
        return {
            "name": "gatewards-sdk",
            "description": "Gatewards SDK",
            "html_url": "https://github.com/rtahabas/gatewards-sdk",
            "owner": {"avatar_url": "https://github.com/rtahabas.png"},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        fetched_urls.append(url)
        if "/readme/packages/mcp-server" in url:
            return "# Gatewards MCP\n\nGatewards MCP server."
        if "/main/packages/mcp-server/server.json" in url:
            return """
            {
              "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
              "name": "io.github.rtahabas/gatewards-mcp",
              "description": "Gatewards MCP server.",
              "version": "1.0.0",
              "packages": [{"registryType": "npm", "identifier": "@gatewards/mcp-server"}]
            }
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(
            repositoryUrl="https://github.com/rtahabas/gatewards-sdk/tree/main/packages/mcp-server",
        ),
    )

    assert response.server_json.repository is not None
    assert response.server_json.repository.url == "rtahabas/gatewards-sdk"
    assert response.server_json.repository.subfolder == "packages/mcp-server"
    assert response.server_json.documentation == "# Gatewards MCP\n\nGatewards MCP server."
    assert any("/readme/packages/mcp-server" in url for url in fetched_urls)


def test_import_server_source_enriches_server_json_with_readme_config(monkeypatch) -> None:
    def fetch_json(url: str):
        return {
            "name": "anki-mcp-server",
            "description": "MCP server for Anki.",
            "html_url": "https://github.com/ankimcp/anki-mcp-server",
            "owner": {"avatar_url": "https://github.com/ankimcp.png"},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        if "/readme" in url:
            return """
            # Anki MCP Server

            ```json
            {
              "mcpServers": {
                "anki": {
                  "command": "npx",
                  "args": ["-y", "@ankimcp/anki-mcp-server", "--stdio"],
                  "env": {
                    "ANKI_CONNECT_URL": "http://localhost:8765"
                  }
                }
              }
            }
            ```
            """
        if "server.json" in url and "/main/" in url:
            return """
            {
              "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
              "name": "ai.ankimcp/anki-mcp-server",
              "title": "Anki MCP Server",
              "description": "MCP server for Anki flashcards.",
              "version": "0.18.4",
              "packages": [
                {
                  "registryType": "npm",
                  "identifier": "@ankimcp/anki-mcp-server",
                  "version": "0.18.4",
                  "transport": {"type": "stdio"}
                }
              ]
            }
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(repositoryUrl="https://github.com/ankimcp/anki-mcp-server"),
    )

    package = response.server_json.packages[0]
    assert response.source == "server.json"
    assert response.evidence.missing == []
    assert response.server_json.meta is not None
    assert response.server_json.meta["sourceReview"]["llm"]["filesRead"] == [
        "README.md",
        "server.json",
    ]
    assert package.version == "0.18.4"
    assert package.transport is not None
    assert package.transport.type_ == "stdio"
    assert package.transport.command == "npx"
    assert package.transport.args == ["-y", "@ankimcp/anki-mcp-server", "--stdio"]
    assert package.transport.env == {"ANKI_CONNECT_URL": "http://localhost:8765"}
    assert response.packages[0] == package


def test_import_server_source_extracts_readme_mcp_server_config(monkeypatch) -> None:
    def fetch_json(url: str):
        return {
            "name": "anki-mcp-server",
            "description": "MCP server for Anki.",
            "html_url": "https://github.com/ankimcp/anki-mcp-server",
            "owner": {"avatar_url": "https://github.com/ankimcp.png"},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        if "/readme" in url:
            return """
            # Anki MCP Server

            ```json
            {
              "mcpServers": {
                "anki": {
                  "command": "npx",
                  "args": ["-y", "@ankimcp/anki-mcp-server", "--stdio"],
                  "env": {
                    "ANKI_CONNECT_URL": "http://localhost:8765"
                  }
                }
              }
            }
            ```
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(repositoryUrl="https://github.com/ankimcp/anki-mcp-server"),
    )

    package = response.server_json.packages[0]
    assert response.source == "mcp.json"
    assert response.evidence.missing == []
    assert response.server_json.meta is not None
    assert response.server_json.meta["sourceReview"]["llm"]["filesRead"] == ["README.md"]
    assert package.registry_type == "npm"
    assert package.identifier == "@ankimcp/anki-mcp-server"
    assert package.transport is not None
    assert package.transport.command == "npx"
    assert package.transport.args == ["-y", "@ankimcp/anki-mcp-server", "--stdio"]
    assert package.transport.env == {"ANKI_CONNECT_URL": "http://localhost:8765"}
