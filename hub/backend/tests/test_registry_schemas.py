import pytest

from app.modules.registry.schemas import RegistryServerVersionCreate


def registry_payload(**overrides):
    payload = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools for forecasts",
        "documentation": "# Weather MCP\n\nUse this server for forecast tools.",
        "version": "1.0.0",
        "websiteUrl": "https://example.com/weather",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/weather-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ],
        "_meta": {
            "io.modelcontextprotocol.registry/publisher-provided": {"category": "weather"}
        },
    }
    payload.update(overrides)
    return payload


def test_mcp_server_document_preserves_aliases_and_meta() -> None:
    payload = RegistryServerVersionCreate(**registry_payload())

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["$schema"].endswith("/server.schema.json")
    assert serialized["websiteUrl"] == "https://example.com/weather"
    assert serialized["documentation"].startswith("# Weather MCP")
    assert serialized["_meta"]["io.modelcontextprotocol.registry/publisher-provided"] == {
        "category": "weather"
    }


def test_mcp_server_document_to_json_dict_serializes_llm_context() -> None:
    payload = RegistryServerVersionCreate(**registry_payload())

    serialized = payload.to_json_dict()

    assert serialized["$schema"].endswith("/server.schema.json")
    assert serialized["websiteUrl"] == "https://example.com/weather"
    assert serialized["_meta"]["io.modelcontextprotocol.registry/publisher-provided"] == {
        "category": "weather"
    }


def test_mcpb_packages_are_allowed_in_hub() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[
                {
                    "registryType": "mcpb",
                    "identifier": "example.mcpb",
                    "version": "1.0.0",
                }
            ]
        )
    )

    assert payload.packages[0].registry_type == "mcpb"


def test_package_metadata_accepts_official_snake_case_manifest_fields() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            name="io.github.browserbase/mcp-server-browserbase",
            packages=[
                {
                    "registry_type": "npm",
                    "registry_base_url": "https://registry.npmjs.org",
                    "identifier": "@browserbasehq/mcp",
                    "version": "2.2.0",
                    "transport": {"type": "stdio"},
                    "environment_variables": [
                        {
                            "description": "Your Browserbase API key",
                            "is_required": True,
                            "format": "string",
                            "is_secret": True,
                            "name": "BROWSERBASE_API_KEY",
                        }
                    ],
                },
                {
                    "registry_type": "oci",
                    "identifier": "browserbasehq/mcp-server-browserbase",
                    "runtime_hint": "docker",
                    "environment_variables": [
                        {
                            "description": "Your Browserbase Project ID",
                            "is_required": True,
                            "format": "string",
                            "is_secret": False,
                            "name": "BROWSERBASE_PROJECT_ID",
                        }
                    ],
                },
            ],
        )
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["packages"][0]["registryType"] == "npm"
    assert serialized["packages"][0]["registryBaseUrl"] == "https://registry.npmjs.org"
    assert serialized["packages"][0]["environmentVariables"] == [
        {
            "description": "Your Browserbase API key",
            "value": "",
            "default": "",
            "format": "string",
            "isRequired": True,
            "isSecret": True,
            "name": "BROWSERBASE_API_KEY",
        }
    ]
    assert serialized["packages"][1]["registryType"] == "oci"
    assert serialized["packages"][1]["runtimeHint"] == "docker"
    assert serialized["packages"][1]["environmentVariables"][0]["isRequired"] is True


def test_package_arguments_distinguish_options_from_launch_args() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[
                {
                    "registry_type": "npm",
                    "identifier": "@example/weather-mcp",
                    "transport": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@example/weather-mcp", "--stdio"],
                    },
                    "package_arguments": [
                        {
                            "name": "port",
                            "flag": "-p, --port",
                            "requires_value": True,
                            "description": "HTTP port for local mode.",
                            "format": "integer",
                            "include_in_launch": False,
                        },
                        {
                            "name": "host",
                            "flag": "-h, --host <host>",
                            "description": "Host for HTTP transport.",
                            "format": "string",
                        },
                        {
                            "name": "login",
                            "flag": "--login [url]",
                            "description": "Login callback URL.",
                            "format": "uri",
                        },
                        {
                            "name": "config",
                            "flag": "--config",
                            "value": "<path>",
                            "description": "Config file path.",
                            "format": "file",
                        },
                        {
                            "value": "--stdio",
                            "include_in_launch": True,
                        },
                    ],
                }
            ]
        )
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["packages"][0]["transport"]["args"] == [
        "-y",
        "@example/weather-mcp",
        "--stdio",
    ]
    assert serialized["packages"][0]["packageArguments"] == [
        {
            "name": "port",
            "flag": "-p, --port",
            "value": "",
            "requiresValue": True,
            "default": "",
            "description": "HTTP port for local mode.",
            "format": "integer",
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
        },
        {
            "name": "host",
            "flag": "-h, --host",
            "value": "",
            "requiresValue": True,
            "default": "",
            "description": "Host for HTTP transport.",
            "format": "string",
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
        },
        {
            "name": "login",
            "flag": "--login",
            "value": "",
            "requiresValue": True,
            "default": "",
            "description": "Login callback URL.",
            "format": "uri",
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
        },
        {
            "name": "config",
            "flag": "--config",
            "value": "",
            "requiresValue": True,
            "default": "",
            "description": "Config file path.",
            "format": "file",
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
        },
        {
            "name": "",
            "flag": "",
            "value": "--stdio",
            "requiresValue": False,
            "default": "",
            "description": "",
            "format": "string",
            "includeInLaunch": True,
            "options": [],
            "allowedValues": [],
        },
    ]


def test_remote_query_parameters_are_typed_and_serialized() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[],
            remotes=[
                {
                    "type": "streamable-http",
                    "url": "https://weather.example.com/mcp",
                    "headers": [
                        {
                            "name": "Authorization",
                            "description": "Bearer token",
                            "required": True,
                            "secret": True,
                        }
                    ],
                    "query_params": [
                        {
                            "name": "api_key",
                            "description": "Weather API key",
                            "is_required": True,
                            "is_secret": True,
                        }
                    ],
                }
            ],
        )
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["remotes"][0]["headers"][0]["isRequired"] is True
    assert serialized["remotes"][0]["headers"][0]["isSecret"] is True
    assert serialized["remotes"][0]["queryParameters"] == [
        {
            "name": "api_key",
            "value": "",
            "description": "Weather API key",
            "isRequired": True,
            "isSecret": True,
        }
    ]


def test_remote_auth_query_parameters_are_canonicalized() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[],
            remotes=[
                {
                    "type": "streamable-http",
                    "url": "https://mcp.browserbase.com/mcp?browserbaseApiKey={browserbaseApiKey}",
                    "authentication": {
                        "type": "query",
                        "queryParameters": [
                            {
                                "name": "browserbaseApiKey",
                                "value": "",
                                "secret": True,
                                "required": True,
                            },
                            {
                                "name": "modelName",
                                "default": "google/gemini-2.5-flash-lite",
                                "secret": False,
                                "required": False,
                            },
                        ],
                    },
                }
            ],
        )
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["remotes"][0]["url"] == "https://mcp.browserbase.com/mcp"
    assert serialized["remotes"][0]["authentication"] == {"type": "query"}
    assert serialized["remotes"][0]["queryParameters"] == [
        {
            "name": "browserbaseApiKey",
            "value": "",
            "description": "",
            "isRequired": True,
            "isSecret": True,
        },
        {
            "name": "modelName",
            "value": "",
            "description": "",
            "isRequired": False,
            "isSecret": False,
            "default": "google/gemini-2.5-flash-lite",
        },
    ]


def test_remote_url_query_parameters_are_extracted() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[],
            remotes=[
                {
                    "type": "streamable-http",
                    "url": "https://weather.example.com/mcp?apiKey={apiKey}&region=us",
                }
            ],
        )
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["remotes"][0]["url"] == "https://weather.example.com/mcp"
    assert serialized["remotes"][0]["queryParameters"] == [
        {
            "name": "apiKey",
            "value": "",
            "description": "",
            "isRequired": True,
            "isSecret": True,
        },
        {
            "name": "region",
            "value": "us",
            "description": "",
            "isRequired": True,
            "isSecret": False,
        },
    ]


def test_server_definition_requires_package_or_remote_target() -> None:
    with pytest.raises(ValueError, match="at least one package or remote"):
        RegistryServerVersionCreate(**registry_payload(packages=[], remotes=[]))


def test_server_definition_requires_category() -> None:
    with pytest.raises(ValueError, match="at least one category"):
        RegistryServerVersionCreate(**registry_payload(_meta=None))


def test_server_name_requires_namespace() -> None:
    with pytest.raises(ValueError):
        RegistryServerVersionCreate(**registry_payload(name="weather"))


def test_server_version_requires_semver() -> None:
    with pytest.raises(ValueError):
        RegistryServerVersionCreate(**registry_payload(version="latest"))
