from app.modules.imports import service
from app.modules.imports.exceptions import SourceNotFoundError
from app.modules.imports.schemas import ServerSourceImportRequest


def test_source_request_headers_use_github_token_for_github_hosts(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    api_headers = service.source_request_headers(
        "https://api.github.com/repos/acme/weather",
        "application/json",
    )
    raw_headers = service.source_request_headers(
        "https://raw.githubusercontent.com/acme/weather/main/README.md",
        "text/plain",
    )

    assert api_headers["Authorization"] == "Bearer github-token"
    assert raw_headers["Authorization"] == "Bearer github-token"
    assert api_headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_source_request_headers_do_not_send_github_token_to_other_hosts(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    headers = service.source_request_headers("https://example.com/source.json", "application/json")

    assert "Authorization" not in headers
    assert "X-GitHub-Api-Version" not in headers


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
    assert response.evidence.missing == ["package transport command"]


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


def test_import_server_source_uses_raw_readme_when_github_api_is_rate_limited(
    monkeypatch,
) -> None:
    fetched_urls: list[str] = []

    def fetch_json(url: str):
        raise SourceNotFoundError("source metadata could not be loaded")

    def fetch_text(url: str, *, accept: str = "application/json"):
        fetched_urls.append(url)
        if "api.github.com" in url:
            raise SourceNotFoundError("source metadata could not be loaded")
        if "/main/README.md" in url:
            return "# Chrome DevTools MCP\n\nChrome DevTools automation server."
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(
            repositoryUrl="https://github.com/ChromeDevTools/chrome-devtools-mcp"
        ),
    )

    assert response.source == "github"
    assert response.title == "chrome-devtools-mcp"
    assert response.website_url == "https://github.com/ChromeDevTools/chrome-devtools-mcp"
    assert response.server_json.documentation == (
        "# Chrome DevTools MCP\n\nChrome DevTools automation server."
    )
    assert any("raw.githubusercontent.com" in url for url in fetched_urls)
    assert response.evidence.files == ["README.md"]


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
    assert package.transport.args == ["--stdio"]
    assert package.transport.env == {"ANKI_CONNECT_URL": "http://localhost:8765"}
    assert response.server_json.meta["sourceReview"]["llm"]["installCommands"] == [
        "npx @ankimcp/anki-mcp-server@0.18.4 --stdio"
    ]
    assert response.server_json.meta["sourceReview"]["llm"]["commandArguments"] == ["--stdio"]
    assert response.packages[0] == package


def test_import_server_source_does_not_import_package_manager_tokens_as_args(monkeypatch) -> None:
    def fetch_json(url: str):
        return {
            "name": "chrome-devtools-mcp",
            "description": "Chrome DevTools MCP server.",
            "html_url": "https://github.com/ChromeDevTools/chrome-devtools-mcp",
            "owner": {"avatar_url": "https://github.com/ChromeDevTools.png"},
        }

    def fetch_text(url: str, *, accept: str = "application/json"):
        if "/readme" in url:
            return """
            # Chrome DevTools MCP

            ```json
            {
              "mcpServers": {
                "chrome-devtools": {
                  "command": "npx",
                  "args": ["-y", "chrome-devtools-mcp@latest"]
                }
              }
            }
            ```
            """
        if "server.json" in url and "/main/" in url:
            return """
            {
              "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
              "name": "io.github.ChromeDevTools/chrome-devtools-mcp",
              "title": "Chrome DevTools MCP",
              "description": "Chrome DevTools MCP server.",
              "version": "1.4.0",
              "packages": [
                {
                  "registryType": "npm",
                  "identifier": "chrome-devtools-mcp",
                  "version": "1.4.0",
                  "transport": {"type": "stdio"}
                }
              ]
            }
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(
            repositoryUrl="https://github.com/ChromeDevTools/chrome-devtools-mcp"
        ),
    )

    package = response.server_json.packages[0]
    assert response.evidence.missing == []
    assert package.identifier == "chrome-devtools-mcp"
    assert package.version == "1.4.0"
    assert package.transport is not None
    assert package.transport.command == "npx"
    assert package.transport.args == []
    assert response.server_json.meta is not None
    assert response.server_json.meta["sourceReview"]["llm"]["installCommands"] == [
        "npx chrome-devtools-mcp@1.4.0"
    ]
    assert response.server_json.meta["sourceReview"]["llm"]["commandArguments"] == []


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
    assert package.transport.args == ["--stdio"]
    assert package.transport.env == {"ANKI_CONNECT_URL": "http://localhost:8765"}
