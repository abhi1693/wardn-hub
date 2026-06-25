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
              "packages": [{"registryType": "npm", "identifier": "@acme/weather-mcp"}]
            }
            """
        return None

    monkeypatch.setattr(service, "fetch_json", fetch_json)
    monkeypatch.setattr(service, "fetch_text", fetch_text)

    response = service.import_server_source(
        ServerSourceImportRequest(repositoryUrl="https://github.com/acme/weather-mcp"),
    )

    assert response.source == "server.json"
    assert response.server_json["name"] == "io.github.acme/weather-mcp"
    assert response.server_json["documentation"] == "# Weather MCP\n\nWeather forecast tools."
    assert response.server_json["packages"] == [
        {"registryType": "npm", "identifier": "@acme/weather-mcp"}
    ]
    assert response.submission_payload["serverJson"] == response.server_json
    assert response.evidence.files == ["README.md", "server.json"]


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
    assert response.server_json["documentation"] == "# Weather MCP\n\nWeather forecast tools."
    assert response.evidence.missing == ["packages or remotes"]
