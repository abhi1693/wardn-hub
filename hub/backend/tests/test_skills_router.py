from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.skills import router
from app.modules.skills.exceptions import SkillAuditNotFoundError, SkillNotFoundError
from app.modules.skills.schemas import (
    OfficialSkillOwner,
    SkillAuditRead,
    SkillAuditResponse,
    SkillDetailResponse,
    SkillFileRead,
    SkillListResponse,
    SkillOfficialResponse,
    SkillPagination,
    SkillRead,
    SkillSearchResponse,
)


def skill_read(slug: str = "find-skills") -> SkillRead:
    return SkillRead(
        id=f"vercel-labs/skills/{slug}",
        slug=slug,
        name=slug,
        source="vercel-labs/skills",
        sourceType="github",
        sourceOwner="vercel-labs",
        sourceName="skills",
        sourceOwnerUrl="https://github.com/vercel-labs",
        sourceOwnerIconUrl="https://avatars.githubusercontent.com/u/14985020?v=4",
        sourceUrl="https://github.com/vercel-labs/skills",
        installUrl="https://github.com/vercel-labs/skills",
        url=f"https://skills.sh/vercel-labs/skills/{slug}",
        description="Find reusable agent skills.",
        installs=42,
        isOfficial=True,
        auditStatus="warn",
    )


def test_skills_openapi_exposes_public_paths() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert {
        "/api/v1/skills",
        "/api/v1/skills/search",
        "/api/v1/skills/official",
        "/api/v1/skills/{skill_id}",
        "/api/v1/skills/audit/{skill_id}",
        "/api/v1/skills/telemetry/{skill_id}",
    }.issubset(set(schema["paths"]))
    assert schema["paths"]["/api/v1/skills"]["get"]["operationId"] == "skills_list"
    assert schema["paths"]["/api/v1/skills/search"]["get"]["operationId"] == "skills_search"
    assert schema["paths"]["/api/v1/skills/official"]["get"]["operationId"] == "skills_official"
    assert schema["paths"]["/api/v1/skills/{skill_id}"]["get"]["operationId"] == "skills_get"
    assert (
        schema["paths"]["/api/v1/skills/telemetry/{skill_id}"]["post"]["operationId"]
        == "skills_install_telemetry"
    )
    detail_parameters = schema["paths"]["/api/v1/skills/{skill_id}"]["get"]["parameters"]
    assert any(parameter["name"] == "include_bundle" for parameter in detail_parameters)
    assert (
        schema["paths"]["/api/v1/skills/audit/{skill_id}"]["get"]["operationId"]
        == "skills_audit_get"
    )


def test_list_skills_returns_skills_sh_style_payload(monkeypatch) -> None:
    async def list_skills(*args, **kwargs):
        assert kwargs == {
            "view": "trending",
            "page": 0,
            "per_page": 10,
            "query": "find",
            "owner": "vercel-labs",
            "source": "vercel-labs/skills",
            "official": True,
        }
        return SkillListResponse(
            data=[skill_read()],
            pagination=SkillPagination(page=0, perPage=10, total=1, hasMore=False),
        )

    monkeypatch.setattr(router, "list_skills", list_skills)

    response = TestClient(create_app()).get(
        "/api/v1/skills"
        "?view=trending"
        "&per_page=10"
        "&q=find"
        "&owner=vercel-labs"
        "&source=vercel-labs/skills"
        "&official=true"
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": "vercel-labs/skills/find-skills",
                "slug": "find-skills",
                "name": "find-skills",
                "source": "vercel-labs/skills",
                "sourceType": "github",
                "sourceOwner": "vercel-labs",
                "sourceName": "skills",
                "sourceOwnerUrl": "https://github.com/vercel-labs",
                "sourceOwnerIconUrl": "https://avatars.githubusercontent.com/u/14985020?v=4",
                "sourceUrl": "https://github.com/vercel-labs/skills",
                "installUrl": "https://github.com/vercel-labs/skills",
                "url": "https://skills.sh/vercel-labs/skills/find-skills",
                "description": "Find reusable agent skills.",
                "installs": 42,
                "isOfficial": True,
                "isDuplicate": None,
                "auditStatus": "warn",
            }
        ],
        "pagination": {"page": 0, "perPage": 10, "total": 1, "hasMore": False},
    }


def test_search_skills_returns_search_metadata(monkeypatch) -> None:
    async def search_skills(*args, **kwargs):
        assert kwargs == {"query": "react native", "limit": 5, "owner": "expo"}
        return SkillSearchResponse(
            data=[skill_read("react-native")],
            query="react native",
            searchType="semantic",
            count=1,
            durationMs=3,
        )

    monkeypatch.setattr(router, "search_skills", search_skills)

    response = TestClient(create_app()).get(
        "/api/v1/skills/search?q=react%20native&owner=expo&limit=5"
    )

    assert response.status_code == 200
    assert response.json()["searchType"] == "semantic"
    assert response.json()["count"] == 1
    assert response.json()["data"][0]["slug"] == "react-native"


def test_official_skills_groups_by_owner(monkeypatch) -> None:
    generated_at = datetime(2026, 7, 10, tzinfo=UTC)

    async def list_official_skills(*args, **kwargs):
        return SkillOfficialResponse(
            data=[
                OfficialSkillOwner(
                    owner="vercel-labs",
                    sourceOwnerIconUrl="https://avatars.githubusercontent.com/u/14985020?v=4",
                    ownerUrl="https://github.com/vercel-labs",
                    featuredRepo="skills",
                    featuredSkill="find-skills",
                    skills=[skill_read()],
                )
            ],
            totalOwners=1,
            totalSkills=1,
            generatedAt=generated_at,
        )

    monkeypatch.setattr(router, "list_official_skills", list_official_skills)

    response = TestClient(create_app()).get("/api/v1/skills/official")

    assert response.status_code == 200
    assert response.json()["data"][0]["owner"] == "vercel-labs"
    assert response.json()["data"][0]["featuredRepo"] == "skills"
    assert response.json()["totalSkills"] == 1


def test_get_skill_detail_supports_nested_github_source(monkeypatch) -> None:
    async def get_skill_detail(*args, **kwargs):
        assert args[1] == "vercel-labs/skills/find-skills"
        assert kwargs == {"include_bundle": False}
        return SkillDetailResponse(
            id="vercel-labs/skills/find-skills",
            source="vercel-labs/skills",
            slug="find-skills",
            sourceOwner="vercel-labs",
            sourceName="skills",
            sourceOwnerUrl="https://github.com/vercel-labs",
            sourceOwnerIconUrl="https://avatars.githubusercontent.com/u/14985020?v=4",
            sourceUrl="https://github.com/vercel-labs/skills",
            hash="abc123",
            files=[SkillFileRead(path="SKILL.md", contents="# Find skills")],
        )

    monkeypatch.setattr(router, "get_skill_detail", get_skill_detail)

    response = TestClient(create_app()).get("/api/v1/skills/vercel-labs/skills/find-skills")

    assert response.status_code == 200
    assert response.json()["hash"] == "abc123"
    assert response.json()["files"] == [{"path": "SKILL.md", "contents": "# Find skills"}]


def test_get_skill_detail_can_return_complete_bundle(monkeypatch) -> None:
    async def get_skill_detail(*args, **kwargs):
        assert kwargs == {"include_bundle": True}
        return SkillDetailResponse(
            id="vercel-labs/skills/find-skills",
            source="vercel-labs/skills",
            slug="find-skills",
            hash="abc123",
            files=[
                SkillFileRead(path="SKILL.md", contents="# Find skills"),
                SkillFileRead(path="references/api.md", contents="# API"),
                SkillFileRead(
                    path="assets/logo.png",
                    contents="iVBORw0KGgo=",
                    encoding="base64",
                ),
                SkillFileRead(
                    path="scripts/find.sh",
                    contents="#!/bin/sh\n",
                    executable=True,
                ),
            ],
        )

    monkeypatch.setattr(router, "get_skill_detail", get_skill_detail)

    response = TestClient(create_app()).get(
        "/api/v1/skills/vercel-labs/skills/find-skills?include_bundle=true"
    )

    assert response.status_code == 200
    assert response.json()["files"] == [
        {"path": "SKILL.md", "contents": "# Find skills"},
        {"path": "references/api.md", "contents": "# API"},
        {
            "path": "assets/logo.png",
            "contents": "iVBORw0KGgo=",
            "encoding": "base64",
        },
        {
            "path": "scripts/find.sh",
            "contents": "#!/bin/sh\n",
            "executable": True,
        },
    ]


def test_get_skill_detail_returns_404(monkeypatch) -> None:
    async def get_skill_detail(*args, **kwargs):
        raise SkillNotFoundError("skill not found")

    monkeypatch.setattr(router, "get_skill_detail", get_skill_detail)

    response = TestClient(create_app()).get("/api/v1/skills/vercel-labs/skills/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "skill not found"


def test_record_skill_install_telemetry_accepts_valid_snapshot(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    async def record_skill_install(*args, **kwargs):
        calls.append((args[1], kwargs))

    monkeypatch.setattr(router, "record_skill_install", record_skill_install)

    response = TestClient(create_app()).post(
        "/api/v1/skills/telemetry/vercel-labs/skills/find-skills"
        f"?content_hash={'a' * 64}&resolver_version=1"
    )

    assert response.status_code == 204
    assert response.content == b""
    assert calls == [
        (
            "vercel-labs/skills/find-skills",
            {"content_hash": "a" * 64, "resolver_version": "1"},
        )
    ]


def test_record_skill_install_telemetry_rejects_invalid_hash() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/skills/telemetry/vercel-labs/skills/find-skills"
        "?content_hash=invalid&resolver_version=1"
    )

    assert response.status_code == 422


def test_get_skill_audit_returns_partner_results(monkeypatch) -> None:
    audited_at = datetime(2026, 7, 10, tzinfo=UTC)

    async def get_skill_audit(*args, **kwargs):
        assert args[1] == "vercel-labs/skills/find-skills"
        return SkillAuditResponse(
            id="vercel-labs/skills/find-skills",
            source="vercel-labs/skills",
            slug="find-skills",
            contentHash="a" * 64,
            audits=[
                SkillAuditRead(
                    provider="Wardn",
                    slug="wardn",
                    status="pass",
                    summary="No risks detected",
                    auditedAt=audited_at,
                    riskLevel="LOW",
                    categories=["SAFE"],
                )
            ],
        )

    monkeypatch.setattr(router, "get_skill_audit", get_skill_audit)

    response = TestClient(create_app()).get("/api/v1/skills/audit/vercel-labs/skills/find-skills")

    assert response.status_code == 200
    assert response.json()["contentHash"] == "a" * 64
    assert response.json()["audits"][0]["provider"] == "Wardn"
    assert response.json()["audits"][0]["riskLevel"] == "LOW"


def test_get_skill_audit_returns_404_when_no_audits(monkeypatch) -> None:
    async def get_skill_audit(*args, **kwargs):
        raise SkillAuditNotFoundError("skill audits not found")

    monkeypatch.setattr(router, "get_skill_audit", get_skill_audit)

    response = TestClient(create_app()).get("/api/v1/skills/audit/vercel-labs/skills/find-skills")

    assert response.status_code == 404
    assert response.json()["detail"] == "skill audits not found"
