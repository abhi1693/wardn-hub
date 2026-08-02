from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.mcp_skills import router
from app.modules.skills.exceptions import SkillNotFoundError
from app.modules.skills.schemas import (
    SkillAuditRead,
    SkillAuditResponse,
    SkillDetailResponse,
    SkillFileRead,
    SkillRead,
    SkillSearchResponse,
)
from app.modules.users import dependencies


async def fake_session():
    yield object()


async def api_token_with_scopes(*scopes: str):
    return (
        SimpleNamespace(
            id=uuid4(),
            is_active=True,
            is_superuser=False,
            is_global_moderator=False,
            is_global_partner_manager=False,
        ),
        SimpleNamespace(scopes=list(scopes)),
    )


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer wardn_hub_key.secret",
        "Accept": "application/json, text/event-stream",
    }


def mcp_client(monkeypatch, *, scopes: tuple[str, ...] = ("skills:read",)) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session

    async def authenticate_api_token(*args, **kwargs):
        return await api_token_with_scopes(*scopes)

    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)
    return TestClient(app)


def jsonrpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_mcp_server_openapi_path_is_stable() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert "/api/v1/mcp-server" in schema["paths"]
    operation = schema["paths"]["/api/v1/mcp-server"]["post"]
    assert operation["operationId"] == "mcp_skills_endpoint"
    assert operation["summary"] == "Wardn Hub read-only skills MCP server"
    assert "requires a bearer" in operation["description"]
    request_examples = operation["requestBody"]["content"]["application/json"]["examples"]
    assert {"initialize", "toolsList", "searchSkills", "getSkillAudit"}.issubset(
        set(request_examples)
    )
    response_examples = operation["responses"]["200"]["content"]["application/json"]["examples"]
    assert {"initialize", "toolsList", "toolCall"}.issubset(set(response_examples))


def test_mcp_server_requires_bearer_api_token() -> None:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session

    response = TestClient(app).post("/api/v1/mcp-server", json=jsonrpc("initialize"))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "API token authentication required"}


def test_mcp_server_requires_skills_read_scope(monkeypatch) -> None:
    response = mcp_client(monkeypatch, scopes=("catalog:read",)).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc("initialize"),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "API token missing required scope: skills:read"}


def test_mcp_server_initialize_returns_tools_capability(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers={**auth_headers(), "MCP-Protocol-Version": "2025-11-25"},
        json=jsonrpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["result"]["protocolVersion"] == "2025-11-25"
    assert body["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert body["result"]["serverInfo"]["name"] == "wardn-hub-skills"


def test_mcp_server_tools_list_is_read_only(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc("tools/list"),
    )

    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "search_skills",
        "get_skill",
        "get_skill_audit",
    ]
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools)
    assert all(tool["annotations"]["destructiveHint"] is False for tool in tools)


def test_mcp_server_search_skills_tool_delegates_to_catalog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def search_skills(*args, **kwargs):
        captured.update(kwargs)
        return SkillSearchResponse(
            data=[
                SkillRead(
                    id="owner/repo/code-review",
                    slug="code-review",
                    name="Code Review",
                    source="owner/repo",
                    sourceType="github",
                    sourceOwner="owner",
                    sourceName="repo",
                    url="https://hub.wardnai.dev/skills/owner/repo/code-review",
                    description="Review code.",
                    installs=7,
                    isOfficial=False,
                    auditStatus="pass",
                    auditScore=99,
                    auditRank="S",
                )
            ],
            query="code review",
            searchType="lexical",
            count=1,
            hasMore=False,
            nextCursor=None,
            durationMs=2,
            auditEnabled=True,
        )

    monkeypatch.setattr(router, "search_skills", search_skills)

    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {
                "name": "search_skills",
                "arguments": {
                    "query": "code review",
                    "limit": 5,
                    "category": "developer-tools",
                    "auditStatus": "pass",
                    "official": False,
                },
            },
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["data"][0]["id"] == "owner/repo/code-review"
    assert "owner/repo/code-review" in result["content"][0]["text"]
    assert captured == {
        "query": "code review",
        "limit": 5,
        "owner": None,
        "category": "developer-tools",
        "audit_status": "pass",
        "official": False,
        "cursor": None,
    }


def test_mcp_server_get_skill_returns_snapshot(monkeypatch) -> None:
    async def get_skill_detail(*args, **kwargs):
        assert args[1] == "owner/repo/code-review"
        assert kwargs == {"content_hash": None, "include_bundle": False}
        return SkillDetailResponse(
            id="owner/repo/code-review",
            source="owner/repo",
            slug="code-review",
            hash="a" * 64,
            files=[SkillFileRead(path="SKILL.md", contents="# Code Review")],
            auditEnabled=True,
        )

    monkeypatch.setattr(router, "get_skill_detail", get_skill_detail)

    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {"name": "get_skill", "arguments": {"skillId": "owner/repo/code-review"}},
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["hash"] == "a" * 64
    assert result["structuredContent"]["files"] == [
        {"path": "SKILL.md", "contents": "# Code Review"}
    ]


def test_mcp_server_get_skill_not_found_is_tool_error(monkeypatch) -> None:
    async def get_skill_detail(*args, **kwargs):
        raise SkillNotFoundError("skill not found")

    monkeypatch.setattr(router, "get_skill_detail", get_skill_detail)

    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {"name": "get_skill", "arguments": {"skillId": "owner/repo/missing"}},
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"] == {
        "error": {"code": "not_found", "message": "skill not found"}
    }


def test_mcp_server_get_skill_audit_returns_current_result(monkeypatch) -> None:
    audited_at = datetime(2026, 7, 31, tzinfo=UTC)

    async def get_skill_audit(*args, **kwargs):
        assert args[1] == "owner/repo/code-review"
        assert kwargs == {"content_hash": "a" * 64}
        return SkillAuditResponse(
            id="owner/repo/code-review",
            source="owner/repo",
            slug="code-review",
            contentHash="a" * 64,
            audit=SkillAuditRead(
                scannerName="Cisco AI Skill Scanner",
                scannerVersion="2.0.12",
                policyName="default",
                policyVersion="1.0",
                policyFingerprint="b" * 64,
                status="pass",
                summary="No risks detected",
                auditedAt=audited_at,
                riskLevel="low",
                score=99,
                rank="S",
                scoreDeductions=[],
                findings=[],
                analyzers=["static_analyzer"],
                scanDurationMs=12,
            ),
        )

    monkeypatch.setattr(router, "get_skill_audit", get_skill_audit)

    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {
                "name": "get_skill_audit",
                "arguments": {
                    "skillId": "owner/repo/code-review",
                    "contentHash": "a" * 64,
                },
            },
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["contentHash"] == "a" * 64
    assert result["structuredContent"]["audit"]["status"] == "pass"


def test_mcp_server_invalid_tool_arguments_are_jsonrpc_error(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {"name": "search_skills", "arguments": {"query": "ai"}},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32602
    assert body["error"]["message"].startswith("query:")


def test_mcp_server_rejects_non_object_tool_arguments(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json=jsonrpc(
            "tools/call",
            {"name": "search_skills", "arguments": []},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] == {"code": -32602, "message": "arguments must be an object"}


def test_mcp_server_accepts_initialized_notification(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers=auth_headers(),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status_code == 202
    assert response.content == b""


def test_mcp_server_rejects_unsupported_protocol_header(monkeypatch) -> None:
    response = mcp_client(monkeypatch).post(
        "/api/v1/mcp-server",
        headers={**auth_headers(), "MCP-Protocol-Version": "2024-01-01"},
        json=jsonrpc("initialize"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsupported MCP protocol version"}
