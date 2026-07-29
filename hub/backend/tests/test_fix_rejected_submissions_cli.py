from __future__ import annotations

import copy
import json
from io import StringIO
from typing import Any

from app.cli import fix_rejected_submissions as cli


class FakeClient:
    def __init__(self, submissions: list[dict[str, Any]] | None = None) -> None:
        self.submissions = submissions or []
        self.fixed: list[tuple[str, dict[str, Any]]] = []

    def list_submissions(self) -> list[dict[str, Any]]:
        return self.submissions

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        for submission in self.submissions:
            if submission["id"] == submission_id:
                return submission
        raise AssertionError(f"unknown submission {submission_id}")

    def fix_submission(self, submission_id: str, server_json: dict[str, Any]) -> dict[str, Any]:
        self.fixed.append((submission_id, server_json))
        for submission in self.submissions:
            if submission["id"] == submission_id:
                submission["serverJson"] = server_json
                submission["name"] = server_json["name"]
                submission["version"] = server_json["version"]
                submission["status"] = "submitted"
                return submission
        raise AssertionError(f"unknown submission {submission_id}")


class FakeReviewer:
    def __init__(self, server_json: dict[str, Any] | None = None) -> None:
        self.server_json = server_json or complete_server_json()
        self.prompts: list[str] = []
        self.environments: list[dict[str, str]] = []

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        self.prompts.append(prompt)
        self.environments.append(environment)
        return fix_result_json(
            "fixed",
            updated_server_json=self.server_json,
        )


def fix_result_json(
    decision: str,
    *,
    updated_server_json: dict[str, Any] | None = None,
    missing_information: list[str] | None = None,
) -> str:
    payload = {
        "decision": decision,
        "updatedServerJson": (
            structured_fix_server_json(updated_server_json)
            if updated_server_json is not None
            else None
        ),
        "summary": "Fixed metadata.",
        "sourceFilesRead": ["https://github.com/example/weather/README.md"],
        "missingInformation": missing_information or [],
    }
    return json.dumps(payload)


def structured_fix_server_json(server_json: dict[str, Any]) -> dict[str, Any]:
    structured = copy.deepcopy(server_json)
    for package in structured.get("packages", []):
        transport = package.get("transport")
        if not isinstance(transport, dict):
            continue
        env = transport.get("env")
        if isinstance(env, dict):
            transport["env"] = [
                {"name": str(name), "value": str(value)}
                for name, value in env.items()
            ]
    return structured


def complete_server_json(version: str = "1.0.0") -> dict[str, Any]:
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools.",
        "documentation": "# Weather\n\nUse this server for forecast tools.",
        "version": version,
        "websiteUrl": "https://github.com/example/weather",
        "repository": {
            "type": "git",
            "source": "github",
            "url": "https://github.com/example/weather",
            "subfolder": "",
            "branch": "main",
            "tag": "",
        },
        "packages": [
            {
                "registryType": "npm",
                "registryBaseUrl": "https://registry.npmjs.org",
                "identifier": "@example/weather",
                "version": version,
                "runtimeHint": "node",
                "transport": {
                    "type": "stdio",
                    "command": "npx",
                    "args": [],
                    "env": {},
                },
                "environmentVariables": [],
                "packageArguments": [],
            }
        ],
        "remotes": [],
        "icons": [],
        "_meta": {
            "categories": ["developer-tools"],
            "registryNamespace": {
                "namespace": "io.github.example",
                "type": "github",
                "authority": "example",
                "verificationStatus": "verified",
                "verificationMethod": "github_owner",
                "evidenceUrl": "https://github.com/example/weather",
                "source": "github",
            },
            "sourceReview": {
                "llm": {
                    "filesRead": ["https://github.com/example/weather/README.md"],
                    "installCommands": ["npx @example/weather"],
                    "commandArguments": [],
                    "environmentVariables": [],
                    "prerequisites": [],
                    "capabilitiesReviewed": True,
                    "limitationsReviewed": True,
                    "unknowns": [],
                }
            },
        },
    }


def rejected_submission(
    *,
    submission_id: str = "sub-1",
    status: str = "rejected",
    updated_at: str = "2026-06-28T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": submission_id,
        "name": "io.github.example/weather",
        "version": "1.0.0",
        "status": status,
        "submissionType": "new_server",
        "ownerUserId": "superuser-1",
        "ownerOrganizationId": None,
        "rejectionMessage": "Add complete source review evidence.",
        "serverJson": complete_server_json(),
        "validationResult": {"status": "failed", "checks": []},
        "updatedAt": updated_at,
    }


def test_build_fix_prompt_uses_db_context_without_token_or_api_instructions() -> None:
    client = FakeClient([rejected_submission()])
    context = cli.build_fix_context(client, client.submissions[0])

    prompt = cli.build_fix_prompt(context)

    assert "Fix this Wardn Hub draft or rejected MCP server submission" in prompt
    assert "Submission ID: sub-1" in prompt
    assert "Current submit/review feedback: Add complete source review evidence." in prompt
    assert "Wardn Hub submission JSON snapshot" in prompt
    assert "Submitted MCP server model JSON from to_json_dict()" in prompt
    assert "Do not call Wardn Hub API endpoints." in prompt
    assert "The database fix controller will apply your returned serverJson" in prompt
    assert 'If submissionType is "new_server", keep serverJson.version' in prompt
    assert "transport-enforced output schema" in prompt
    assert "updatedServerJson" in prompt
    assert "nested server object required by the output schema" in prompt
    assert "Do not JSON-encode it as a string." in prompt
    assert "transport.env as an array of name/value entries" in prompt
    assert "preserves official registry, import, publisher" in prompt
    assert "Read every `.md` file you can find" in prompt
    assert "QUICKSTART" in prompt
    assert "cannot_fix" in prompt
    assert 'numeric and boolean-looking defaults such as "300", "true", and "0"' in prompt
    assert 'Use format "file" when the value is a path to a file' in prompt
    assert "GOOGLE_APPLICATION_CREDENTIALS" in prompt
    assert "missingInformation" in prompt
    assert "validates against this schema" not in prompt
    assert "WARDN_HUB_TOKEN" not in prompt
    assert "GET /submissions" not in prompt
    assert "PUT /submissions" not in prompt
    assert prompt.index("System fix mode:") < prompt.index("Submission context:")
    assert prompt.index("Required output:") < prompt.index("Submission context:")
    assert prompt.index("Submission context:") < prompt.index("Submission ID: sub-1")


def test_build_fix_prompt_keeps_submission_data_after_stable_prefix() -> None:
    client = FakeClient([rejected_submission(submission_id="sub-cache-test")])
    context = cli.build_fix_context(client, client.submissions[0])

    prompt = cli.build_fix_prompt(context)

    assert prompt.startswith("Fix this Wardn Hub draft or rejected MCP server submission")
    assert prompt.index("System fix mode:") < prompt.index("sub-cache-test")
    assert prompt.index("Required output:") < prompt.index("sub-cache-test")
    snapshot = prompt[prompt.index("Wardn Hub submission JSON snapshot:"):]
    assert snapshot.index('"id"') < snapshot.index('"name"') < snapshot.index('"rejectionMessage"')


def test_fix_loop_applies_updated_server_json_and_submits() -> None:
    client = FakeClient(
        [
            rejected_submission(submission_id="newer", updated_at="2026-06-29T10:00:00Z"),
            rejected_submission(submission_id="oldest", updated_at="2026-06-28T10:00:00Z"),
        ]
    )
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert len(reviewer.prompts) == 1
    assert "Submission ID: oldest" in reviewer.prompts[0]
    assert reviewer.environments[0]["WARDN_HUB_FIX_SUBMISSION_ID"] == "oldest"
    assert client.fixed[0][0] == "oldest"
    assert client.get_submission("oldest")["status"] == "submitted"
    assert "Submitted oldest for review." in stdout.getvalue()


def test_fix_loop_preserves_new_server_registry_version() -> None:
    server_json = complete_server_json(version="2026.5.54")
    server_json["packages"][0]["version"] = "2026.5.54"
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer(server_json)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    applied_server_json = client.fixed[0][1]
    assert applied_server_json["version"] == "1.0.0"
    assert applied_server_json["packages"][0]["version"] == "2026.5.54"
    assert client.get_submission("sub-1")["version"] == "1.0.0"


def test_fix_loop_skips_cannot_fix_decision() -> None:
    class CannotFixReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            self.prompts.append(prompt)
            self.environments.append(environment)
            return fix_result_json(
                "cannot_fix",
                missing_information=["Missing official repository URL."],
            )

    client = FakeClient([rejected_submission()])
    reviewer = CannotFixReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert client.fixed == []
    assert "Reviewer could not fix sub-1" in stdout.getvalue()


def test_fix_loop_reports_failure_when_llm_omits_server_json() -> None:
    class MissingJsonReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            self.prompts.append(prompt)
            self.environments.append(environment)
            return "Decision: fixed\n\nSummary: fixed it"

    client = FakeClient([rejected_submission()])
    reviewer = MissingJsonReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 1
    assert client.fixed == []
    assert (
        "LLM did not return a valid schema-constrained fix response"
        in stdout.getvalue()
    )


def test_dry_run_prints_prompt_without_running_reviewer() -> None:
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=True,
        stdout=stdout,
    )

    assert result == 0
    assert reviewer.prompts == []
    assert client.fixed == []
    assert "Fix this Wardn Hub draft or rejected MCP server submission" in stdout.getvalue()


def test_extract_fix_result_reads_structured_json() -> None:
    server_json = complete_server_json()
    findings = fix_result_json("fixed", updated_server_json=server_json)

    result = cli.extract_fix_result(findings)

    assert result is not None
    assert result.decision == "fixed"
    assert result.updated_server_json is not None
    assert result.updated_server_json.to_registry_json(server_json) == server_json


def test_extract_fix_result_accepts_schema_only_json() -> None:
    server_json = complete_server_json()
    findings = json.dumps(
        {
            "decision": "fixed",
            "updatedServerJson": structured_fix_server_json(server_json),
            "summary": "Verified and repaired metadata.",
            "sourceFilesRead": ["https://github.com/example/weather/README.md"],
            "missingInformation": [],
        }
    )

    result = cli.extract_fix_result(findings)

    assert result is not None
    assert result.decision == "fixed"
    assert result.updated_server_json is not None
    assert result.updated_server_json.name == server_json["name"]


def test_fix_output_schema_requires_every_contract_field() -> None:
    schema = cli.FIX_DECISION_OUTPUT_SCHEMA

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert '"additionalProperties": true' not in json.dumps(schema)
    updated_server_options = schema["properties"]["updatedServerJson"]["anyOf"]
    assert {"type": "null"} in updated_server_options
    assert any(
        option.get("$ref") == "#/$defs/SubmissionFixServerJson"
        for option in updated_server_options
    )
    package_argument_schema = schema["$defs"]["SubmissionFixPackageArgument"]
    assert package_argument_schema["properties"]["default"]["type"] == "string"
    assert set(package_argument_schema["required"]) == set(
        package_argument_schema["properties"]
    )


def test_extract_fix_result_rejects_schema_only_json_with_missing_fields() -> None:
    assert cli.extract_fix_result(json.dumps({"decision": "skip"})) is None


def test_extract_fix_result_rejects_legacy_encoded_server_json() -> None:
    findings = json.dumps(
        {
            "decision": "fixed",
            "updatedServerJson": json.dumps(complete_server_json()),
            "summary": "Tried to repair metadata.",
            "sourceFilesRead": [],
            "missingInformation": [],
        }
    )

    assert cli.extract_fix_result(findings) is None


def test_extract_fix_result_allows_markdown_fences_inside_nested_documentation() -> None:
    server_json = complete_server_json()
    server_json["documentation"] = (
        "## Installation\n\n"
        "```bash\n"
        "npx @example/weather\n"
        "```\n\n"
        "```json\n"
        '{"mcpServers":{"weather":{"command":"npx"}}}\n'
        "```"
    )
    findings = fix_result_json("fixed", updated_server_json=server_json)

    result = cli.extract_fix_result(findings)

    assert result is not None
    assert result.updated_server_json is not None
    assert result.updated_server_json.documentation == server_json["documentation"]


def test_extract_fix_result_rejects_non_string_package_argument_defaults() -> None:
    server_json = complete_server_json()
    server_json["packages"][0]["packageArguments"] = [
        {
            "name": "",
            "flag": "--max-rows",
            "value": "",
            "default": 1000,
            "description": "Maximum rows returned.",
            "format": "integer",
            "requiresValue": True,
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
            "isRequired": False,
            "isSecret": False,
        }
    ]

    findings = fix_result_json("fixed", updated_server_json=server_json)

    assert cli.extract_fix_result(findings) is None


def test_nested_fix_contract_accepts_stringified_scalar_argument_defaults() -> None:
    server_json = complete_server_json()
    server_json["packages"][0]["packageArguments"] = [
        {
            "name": "",
            "flag": flag,
            "value": "",
            "default": default,
            "description": description,
            "format": format_,
            "requiresValue": requires_value,
            "includeInLaunch": False,
            "options": [],
            "allowedValues": [],
            "isRequired": False,
            "isSecret": False,
        }
        for flag, default, description, format_, requires_value in (
            ("--rest-cache-ttl", "300", "REST cache TTL.", "integer", True),
            ("--max-rows", "1000", "Maximum rows returned.", "integer", True),
            ("--read-only", "true", "Keep queries read-only.", "boolean", False),
            ("--http-port", "0", "Optional HTTP port.", "integer", True),
        )
    ]

    result = cli.extract_fix_result(
        fix_result_json("fixed", updated_server_json=server_json)
    )

    assert result is not None
    assert result.updated_server_json is not None
    registry_json = result.updated_server_json.to_registry_json(server_json)
    validated = cli.RegistryServerVersionCreate.model_validate(registry_json)
    assert [
        argument.default
        for argument in validated.packages[0].package_arguments
    ] == ["300", "1000", "true", "0"]


def test_nested_fix_contract_converts_maps_and_preserves_system_metadata() -> None:
    current_server_json = complete_server_json()
    current_server_json["_meta"]["wardnImport"] = {
        "source": "modelcontextprotocol-registry",
        "upstreamVersion": "1.0.0",
    }
    current_server_json["_meta"]["io.modelcontextprotocol.registry/official"] = {
        "status": "active",
        "isLatest": True,
    }
    current_server_json["repository"]["customRepositoryField"] = "preserved"
    current_server_json["packages"][0]["fileSha256"] = "sha256:preserved"
    current_server_json["packages"][0]["transport"]["customTransportField"] = "preserved"
    updated_server_json = complete_server_json()
    updated_server_json["packages"][0]["transport"]["env"] = {
        "WEATHER_API_TOKEN": "",
    }
    updated_server_json["packages"][0]["environmentVariables"] = [
        {
            "name": "WEATHER_API_TOKEN",
            "description": "Weather API token.",
            "value": "",
            "default": "",
            "format": "string",
            "isRequired": True,
            "isSecret": True,
        }
    ]

    result = cli.extract_fix_result(
        fix_result_json("fixed", updated_server_json=updated_server_json)
    )

    assert result is not None
    assert result.updated_server_json is not None
    registry_json = result.updated_server_json.to_registry_json(current_server_json)
    assert registry_json["packages"][0]["transport"]["env"] == {
        "WEATHER_API_TOKEN": "",
    }
    assert registry_json["_meta"]["wardnImport"]["upstreamVersion"] == "1.0.0"
    assert registry_json["_meta"]["io.modelcontextprotocol.registry/official"] == {
        "status": "active",
        "isLatest": True,
    }
    assert registry_json["repository"]["customRepositoryField"] == "preserved"
    assert registry_json["packages"][0]["fileSha256"] == "sha256:preserved"
    assert (
        registry_json["packages"][0]["transport"]["customTransportField"]
        == "preserved"
    )
    cli.RegistryServerVersionCreate.model_validate(registry_json)


def test_extract_fix_result_rejects_markdown_only_output() -> None:
    server_json = complete_server_json()
    findings = (
        "Decision: fixed\n\n"
        "Updated serverJson:\n"
        "```json\n"
        f"{json.dumps(server_json)}\n"
        "```"
    )

    assert cli.extract_fix_result(findings) is None


def test_extract_fix_result_rejects_legacy_fenced_json() -> None:
    findings = (
        "Fix result JSON:\n"
        "```json\n"
        + fix_result_json("fixed", updated_server_json=complete_server_json())
        + "\n```"
    )

    assert cli.extract_fix_result(findings) is None


def test_parser_uses_app_server_defaults() -> None:
    args = cli.build_parser().parse_args(["--submission-id", "sub-1", "--dry-run"])

    assert args.submission_id == "sub-1"
    assert args.dry_run is True
    assert hasattr(args, "codex_app_server_url")
    assert not hasattr(args, "review_command")


def test_main_configures_transport_enforced_fix_schema(monkeypatch) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class CapturingReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubDatabaseFixClient", object)
    monkeypatch.setattr(cli, "validate_database_fix_client", lambda _client: {"id": "database"})
    monkeypatch.setattr(cli, "CodexAppServerReviewer", CapturingReviewer)
    monkeypatch.setattr(cli, "fix_loop", lambda **_kwargs: 0)

    result = cli.main(
        [
            "--codex-app-server-url",
            "ws://127.0.0.1:41237",
            "--once",
        ]
    )

    assert result == 0
    assert (
        captured_reviewers[0]["structured_output_schema"]
        == cli.FIX_DECISION_OUTPUT_SCHEMA
    )
