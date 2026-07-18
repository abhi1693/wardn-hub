import logging
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import manage
from app.cli import skills

RESOLVED_COMMIT_SHA = "a" * 40


def github_import_args(
    *,
    owner: str = "acme",
    recursive: bool = False,
    subfolder: str = "skills",
    github_token: str = "github-token",
    timeout_seconds: float = 3.0,
) -> Namespace:
    return Namespace(
        owner=owner,
        recursive=recursive,
        subfolder=subfolder,
        github_token=github_token,
        timeout_seconds=timeout_seconds,
    )


def import_repository(
    name: str,
    *,
    owner: str = "acme",
    default_branch: str = "main",
) -> skills.GitHubImportRepository:
    return skills.GitHubImportRepository(
        repo=skills.GitHubRepository(
            owner=owner,
            repo=name,
            url=f"https://github.com/{owner}/{name}",
        ),
        default_branch=default_branch,
    )


def repository_listing(
    *repositories: skills.GitHubImportRepository,
    owner: str = "acme",
    account_type: str = "Organization",
    listed_count: int | None = None,
) -> skills.GitHubRepositoryListing:
    return skills.GitHubRepositoryListing(
        owner=skills.GitHubOwner(
            login=owner,
            account_type=account_type,  # type: ignore[arg-type]
            avatar_url=f"https://avatars.example/{owner}.png",
        ),
        repositories=list(repositories),
        listed_count=listed_count if listed_count is not None else len(repositories),
    )


def refresh_target(
    slug: str,
    subfolder: str,
    *,
    current_hash: str | None = "old-hash",
    ref: str = "main",
    source: str = "acme/agent-skills",
) -> skills.SkillRefreshTarget:
    repository: dict[str, object] = {
        "type": "git",
        "source": "github",
        "url": f"https://github.com/{source}",
        "subfolder": subfolder,
        "branch": ref,
    }
    return skills.SkillRefreshTarget(
        skill_id=f"skill-id-{slug}",
        current_snapshot_id=f"snapshot-id-{slug}",
        current_hash=current_hash,
        source=source,
        slug=slug,
        repository=repository,
        repo=skills.parse_github_repository_url(f"https://github.com/{source}"),
        subfolder=subfolder,
        ref=ref,
    )


def test_parse_frontmatter_extracts_name_and_description() -> None:
    assert skills.parse_frontmatter(
        """---
name: weather-skill
description: Helps with weather APIs.
---

# Weather Skill
"""
    ) == {
        "name": "weather-skill",
        "description": "Helps with weather APIs.",
    }


def test_read_skill_add_input_infers_fields(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """---
name: Weather Skill
description: Helps with weather APIs.
---
""",
        encoding="utf-8",
    )

    payload = skills.read_skill_add_input(
        Namespace(
            source="acme/agent-skills",
            skill_file=str(skill_file),
            slug="",
            name="",
            description="",
            source_type="github",
            source_owner="",
            source_name="",
            source_owner_url="",
            source_owner_icon_url="",
            source_url="",
            install_url="",
            website_url="",
            repository_url="",
        )
    )

    assert payload.source == "acme/agent-skills"
    assert payload.source_owner == "acme"
    assert payload.source_name == "agent-skills"
    assert payload.source_owner_url == "https://github.com/acme"
    assert payload.source_owner_icon_url == ""
    assert payload.source_url == "https://github.com/acme/agent-skills"
    assert payload.slug == "weather-skill"
    assert payload.name == "Weather Skill"
    assert payload.description == "Helps with weather APIs."
    assert payload.install_url == "https://github.com/acme/agent-skills"


def test_read_skill_add_input_rejects_invalid_source(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("---\nname: Weather\n---\n", encoding="utf-8")

    with pytest.raises(skills.SkillCliError, match="owner/repo"):
        skills.read_skill_add_input(
            Namespace(
                source="acme",
                skill_file=str(skill_file),
                slug="",
                name="",
                description="",
                source_type="github",
                source_owner="",
                source_name="",
                source_owner_url="",
                source_owner_icon_url="",
                source_url="",
                install_url="",
                website_url="",
                repository_url="",
            )
        )


def test_parse_github_repository_url_supports_tree_subpath() -> None:
    repo = skills.parse_github_repository_url(
        "https://github.com/acme/agent-skills/tree/main/skills/weather"
    )

    assert repo.owner == "acme"
    assert repo.repo == "agent-skills"
    assert repo.source == "acme/agent-skills"
    assert repo.ref == "main"
    assert repo.path == "skills/weather"


def test_skill_refresh_target_uses_recorded_exact_location() -> None:
    repository = {
        "type": "git",
        "source": "github",
        "url": "https://github.com/acme/agent-skills",
        "subfolder": "skills/weather",
        "branch": "stable",
    }
    skill = SimpleNamespace(
        id="skill-id",
        current_snapshot_id="snapshot-id",
        source="acme/agent-skills",
        slug="weather",
        repository=repository,
    )

    target = skills.skill_refresh_target(skill, "snapshot-hash")

    assert target.id == "acme/agent-skills/weather"
    assert target.skill_path == "skills/weather/SKILL.md"
    assert target.ref == "stable"
    assert target.current_hash == "snapshot-hash"
    assert target.repository == repository


def test_skill_refresh_target_rejects_mismatched_repository() -> None:
    skill = SimpleNamespace(
        id="skill-id",
        current_snapshot_id="snapshot-id",
        source="acme/agent-skills",
        slug="weather",
        repository={
            "type": "git",
            "source": "github",
            "url": "https://github.com/other/agent-skills",
            "subfolder": "skills/weather",
            "branch": "main",
        },
    )

    with pytest.raises(skills.SkillCliError, match="does not match"):
        skills.skill_refresh_target(skill, "snapshot-hash")


def test_skill_refresh_target_requires_recorded_import_branch() -> None:
    skill = SimpleNamespace(
        id="skill-id",
        current_snapshot_id="snapshot-id",
        source="acme/agent-skills",
        slug="weather",
        repository={
            "type": "git",
            "source": "github",
            "url": "https://github.com/acme/agent-skills",
        },
    )

    with pytest.raises(skills.SkillCliError, match="no recorded GitHub branch"):
        skills.skill_refresh_target(skill, "snapshot-hash")


async def test_load_skill_refresh_targets_counts_invalid_current_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_skill = SimpleNamespace(
        id="valid-skill-id",
        current_snapshot_id="valid-snapshot-id",
        source="acme/agent-skills",
        slug="valid",
        repository={
            "type": "git",
            "source": "github",
            "url": "https://github.com/acme/agent-skills",
            "subfolder": "skills/valid",
            "branch": "main",
        },
    )
    invalid_skill = SimpleNamespace(
        id="invalid-skill-id",
        current_snapshot_id=None,
        source="acme/agent-skills",
        slug="invalid",
        repository=None,
    )
    statements: list[str] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, statement: object) -> SimpleNamespace:
            statements.append(str(statement))
            return SimpleNamespace(
                all=lambda: [
                    (valid_skill, "valid-hash", "active", True, valid_skill.id),
                    (invalid_skill, None, None, None, None),
                ]
            )

    monkeypatch.setattr(skills, "AsyncSessionLocal", FakeSession)

    targets, issues = await skills.load_skill_refresh_targets()

    assert [target.slug for target in targets] == ["valid"]
    assert issues == [
        skills.SkillRefreshIssue(
            skill_id="acme/agent-skills/invalid",
            reason="skill has no active latest current snapshot",
        )
    ]
    assert "LEFT OUTER JOIN skill_snapshots" in statements[0]


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        (
            b"first\nsecond\x00",
            "GitHub file contains a NUL byte at offset 12 (line 2): "
            "skills/binary/SKILL.md",
        ),
        (
            b"\xff",
            "GitHub file is not UTF-8 text: skills/binary/SKILL.md",
        ),
        (
            b"# Skill\n\x1b",
            "GitHub file contains unsupported control character U+001B at "
            "character offset 8: skills/binary/SKILL.md",
        ),
    ],
)
async def test_github_raw_file_rejects_invalid_text(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    expected_error: str,
) -> None:
    async def fake_get(url: str, *, follow_redirects: bool) -> SimpleNamespace:
        assert url.endswith("/acme/agent-skills/main/skills/binary/SKILL.md")
        assert follow_redirects is False
        return SimpleNamespace(
            status_code=200,
            content=content,
            text="",
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.InvalidSkillTextError) as exc_info:
            await client.raw_file(repo, "main", "skills/binary/SKILL.md")

    assert str(exc_info.value) == expected_error


async def test_github_raw_file_http_error_is_not_invalid_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    async def fake_get(url: str, *, follow_redirects: bool) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        assert follow_redirects is False
        return SimpleNamespace(
            status_code=500,
            content=b"",
            headers={"x-github-request-id": "REQUEST-500"},
            text="upstream failure",
        )

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    monkeypatch.setattr(skills.asyncio, "sleep", fake_sleep)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillCliError) as exc_info:
            await client.raw_file(repo, "main", "skills/weather/SKILL.md")

    assert not isinstance(exc_info.value, skills.InvalidSkillTextError)
    assert str(exc_info.value) == (
        "GitHub raw file fetch failed for skills/weather/SKILL.md "
        "(HTTP 500, request ID REQUEST-500): upstream failure"
    )
    assert calls == 4
    assert sleeps == [1, 2, 4]


async def test_github_raw_file_encodes_ref_and_path_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, *, follow_redirects: bool) -> SimpleNamespace:
        assert url.endswith(
            "/feature/api%23v2/skills/weather/references/a%23b%3F%25%20file.txt"
        )
        assert follow_redirects is False
        return SimpleNamespace(status_code=200, content=b"reference", text="")

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        contents = await client.raw_file_bytes(
            repo,
            "feature/api#v2",
            "skills/weather/references/a#b?% file.txt",
        )

    assert contents == b"reference"


async def test_github_repository_metadata_rejects_private_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str) -> SimpleNamespace:
        assert url.endswith("/repos/acme/agent-skills")
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "default_branch": "main",
                "private": True,
                "visibility": "private",
                "owner": {"avatar_url": ""},
            },
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillCliError, match="only supports public repositories"):
            await client.repository_metadata(repo)


@pytest.mark.parametrize("inactive_field", ["fork", "archived", "disabled"])
async def test_github_repository_metadata_rejects_inactive_repository(
    monkeypatch: pytest.MonkeyPatch,
    inactive_field: str,
) -> None:
    async def fake_get(url: str) -> SimpleNamespace:
        payload = {
            "default_branch": "main",
            "private": False,
            "visibility": "public",
            "fork": False,
            "archived": False,
            "disabled": False,
            "owner": {"avatar_url": ""},
        }
        payload[inactive_field] = True
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: payload,
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillCliError, match="not active"):
            await client.repository_metadata(repo)


async def test_github_repository_metadata_rejects_transferred_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "full_name": "other/agent-skills",
                "default_branch": "main",
                "private": False,
                "visibility": "public",
                "fork": False,
                "archived": False,
                "disabled": False,
                "owner": {"avatar_url": ""},
            },
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillCliError, match="moved to another owner"):
            await client.repository_metadata(repo)


async def test_github_lists_paginated_active_organization_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []
    next_url = "https://api.github.com/organizations/42/repos?page=2&per_page=100"

    def repository_payload(
        name: str,
        *,
        private: bool = False,
        fork: bool = False,
        archived: bool = False,
        disabled: bool = False,
        default_branch: str | None = "main",
    ) -> dict[str, object]:
        return {
            "name": name,
            "full_name": f"Acme/{name}",
            "private": private,
            "fork": fork,
            "archived": archived,
            "disabled": disabled,
            "visibility": "private" if private else "public",
            "default_branch": default_branch,
        }

    async def fake_get(
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> SimpleNamespace:
        calls.append((url, params))
        if url.endswith("/users/acme"):
            return SimpleNamespace(
                status_code=200,
                text="",
                json=lambda: {
                    "login": "Acme",
                    "type": "Organization",
                    "avatar_url": "https://avatars.example/acme.png",
                },
            )
        if url.endswith("/orgs/Acme/repos"):
            return SimpleNamespace(
                status_code=200,
                text="",
                links={"next": {"url": next_url}},
                json=lambda: [
                    repository_payload("weather"),
                    repository_payload("fork", fork=True),
                    repository_payload("archive", archived=True),
                    repository_payload("private", private=True),
                    repository_payload("disabled", disabled=True),
                ],
            )
        assert url == next_url
        return SimpleNamespace(
            status_code=200,
            text="",
            links={},
            json=lambda: [
                repository_payload("alpha", default_branch="stable"),
                repository_payload("empty", default_branch=None),
                repository_payload("weather"),
            ],
        )

    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        listing = await client.list_active_repositories("acme")

    assert listing.owner == skills.GitHubOwner(
        login="Acme",
        account_type="Organization",
        avatar_url="https://avatars.example/acme.png",
    )
    assert listing.listed_count == 8
    assert [item.repo.source for item in listing.repositories] == [
        "Acme/alpha",
        "Acme/empty",
        "Acme/weather",
    ]
    assert [item.default_branch for item in listing.repositories] == [
        "stable",
        "",
        "main",
    ]
    assert calls[1] == (
        "https://api.github.com/orgs/Acme/repos",
        {
            "type": "public",
            "sort": "full_name",
            "direction": "asc",
            "per_page": "100",
        },
    )
    assert calls[2] == (next_url, None)


async def test_github_lists_user_owned_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_owner(owner: str) -> skills.GitHubOwner:
        assert owner == "octocat"
        return skills.GitHubOwner(login="octocat", account_type="User", avatar_url="")

    async def fake_get(
        url: str,
        *,
        params: dict[str, str],
    ) -> SimpleNamespace:
        assert url == "https://api.github.com/users/octocat/repos"
        assert params["type"] == "owner"
        return SimpleNamespace(status_code=200, text="", links={}, json=lambda: [])

    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "owner", fake_owner)
        monkeypatch.setattr(client._client, "get", fake_get)
        listing = await client.list_active_repositories("octocat")

    assert listing.repositories == []
    assert listing.listed_count == 0


def github_search_repository(name: str, *, owner: str = "acme") -> dict[str, object]:
    return {
        "name": name,
        "full_name": f"{owner}/{name}",
        "private": False,
        "fork": False,
        "archived": False,
        "disabled": False,
        "visibility": "public",
        "default_branch": "main",
        "owner": {
            "login": owner,
            "type": "Organization",
            "avatar_url": f"https://avatars.example/{owner}.png",
        },
    }


def github_code_search_item(name: str, *, owner: str = "acme") -> dict[str, object]:
    return {
        "name": "SKILL.md",
        "path": "skills/example/SKILL.md",
        "repository": github_search_repository(name, owner=owner),
    }


async def test_github_repository_search_streams_pages_and_stops_at_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_search_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubRepositorySearchPage:
        calls.append((query, page))
        item = github_search_repository("one" if page == 1 else "two")
        return skills.GitHubRepositorySearchPage(
            total_count=101,
            incomplete_results=False,
            items=[item],
        )

    filters = skills.GitHubRepositoryFilters(
        organizations=("acme",),
        min_stars=25,
        pushed_after="2026-01-01",
        max_repositories=1,
    )
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_repository_page", fake_search_page)
        iterator = client.iter_repositories(filters, stats).__aiter__()
        first = await anext(iterator)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    assert first.repo.source == "acme/one"
    assert first.owner_avatar_url == "https://avatars.example/acme.png"
    assert len(calls) == 1
    assert calls[0][1] == 1
    assert "org:acme" in calls[0][0]
    assert "stars:>=25" in calls[0][0]
    assert "pushed:>=2026-01-01" in calls[0][0]
    assert stats.listed_repository_count == 1
    assert stats.active_repository_count == 1


async def test_github_recursive_discovery_uses_code_search_and_metadata_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    metadata_calls: list[str] = []

    async def fake_search_code_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubCodeSearchPage:
        calls.append((query, page))
        return skills.GitHubCodeSearchPage(
            total_count=3,
            incomplete_results=False,
            items=[
                github_code_search_item("small"),
                github_code_search_item("large"),
                github_code_search_item("large"),
            ],
        )

    async def fake_repository_metadata(
        repo: skills.GitHubRepository,
    ) -> skills.GitHubRepositoryMetadata:
        metadata_calls.append(repo.source)
        return skills.GitHubRepositoryMetadata(
            default_branch="main",
            owner_avatar_url=f"https://avatars.example/{repo.owner}.png",
            stargazers_count=50 if repo.repo == "large" else 5,
        )

    filters = skills.GitHubRepositoryFilters(all_github=True, min_stars=30)
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_code_page", fake_search_code_page)
        monkeypatch.setattr(client, "repository_metadata", fake_repository_metadata)
        repositories = [
            repository
            async for repository in client.iter_repositories(
                filters,
                stats,
                recursive=True,
                subfolder="skills",
            )
        ]

    assert [repository.repo.source for repository in repositories] == ["acme/large"]
    assert calls == [("filename:SKILL.md path:skills", 1)]
    assert metadata_calls == ["acme/small", "acme/large"]
    assert stats.listed_repository_count == 3
    assert stats.filtered_repository_count == 2
    assert stats.active_repository_count == 1


async def test_github_recursive_code_search_applies_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_calls: list[str] = []

    async def fake_search_code_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubCodeSearchPage:
        return skills.GitHubCodeSearchPage(
            total_count=4,
            incomplete_results=False,
            items=[
                github_code_search_item("blocked", owner="blocked-org"),
                github_code_search_item("blocked-repo"),
                github_code_search_item("sample-skills"),
                github_code_search_item("kept"),
            ],
        )

    async def fake_repository_metadata(
        repo: skills.GitHubRepository,
    ) -> skills.GitHubRepositoryMetadata:
        metadata_calls.append(repo.source)
        return skills.GitHubRepositoryMetadata(
            default_branch="main",
            owner_avatar_url=f"https://avatars.example/{repo.owner}.png",
        )

    filters = skills.GitHubRepositoryFilters(
        all_github=True,
        excluded_organizations=("blocked-org",),
        excluded_repositories=("acme/blocked-repo",),
        excluded_repository_names=("skills",),
    )
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_code_page", fake_search_code_page)
        monkeypatch.setattr(client, "repository_metadata", fake_repository_metadata)
        repositories = [
            repository
            async for repository in client.iter_repositories(
                filters,
                stats,
                recursive=True,
                subfolder="skills",
            )
        ]

    assert [repository.repo.source for repository in repositories] == ["acme/kept"]
    assert metadata_calls == ["acme/kept"]
    assert stats.filtered_repository_count == 3
    assert stats.active_repository_count == 1


async def test_github_recursive_topic_discovery_uses_repository_search_then_skill_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_queries: list[tuple[str, int]] = []
    code_queries: list[tuple[str, int]] = []

    async def fake_search_repository_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubRepositorySearchPage:
        repository_queries.append((query, page))
        return skills.GitHubRepositorySearchPage(
            total_count=2,
            incomplete_results=False,
            items=[
                github_search_repository("without-skill"),
                github_search_repository("with-skill"),
            ],
        )

    async def fake_search_code_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubCodeSearchPage:
        code_queries.append((query, page))
        return skills.GitHubCodeSearchPage(
            total_count=1 if "with-skill" in query else 0,
            incomplete_results=False,
            items=[github_code_search_item("with-skill")] if "with-skill" in query else [],
        )

    filters = skills.GitHubRepositoryFilters(all_github=True, topics=("agents",))
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_repository_page", fake_search_repository_page)
        monkeypatch.setattr(client, "search_code_page", fake_search_code_page)
        repositories = [
            repository
            async for repository in client.iter_repositories(
                filters,
                stats,
                recursive=True,
                subfolder="skills",
            )
        ]

    assert [repository.repo.source for repository in repositories] == ["acme/with-skill"]
    assert len(repository_queries) == 1
    assert "topic:agents" in repository_queries[0][0]
    assert code_queries == [
        ("filename:SKILL.md repo:acme/without-skill path:skills", 1),
        ("filename:SKILL.md repo:acme/with-skill path:skills", 1),
    ]
    assert stats.active_repository_count == 2
    assert stats.filtered_repository_count == 1


async def test_github_recursive_repo_name_discovery_uses_repository_search_then_skill_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_queries: list[tuple[str, int]] = []
    code_queries: list[tuple[str, int]] = []

    async def fake_search_repository_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubRepositorySearchPage:
        repository_queries.append((query, page))
        return skills.GitHubRepositorySearchPage(
            total_count=2,
            incomplete_results=False,
            items=[
                github_search_repository("agent-skills"),
                github_search_repository("prompt-skills"),
            ],
        )

    async def fake_search_code_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubCodeSearchPage:
        code_queries.append((query, page))
        has_skill = "prompt-skills" in query
        return skills.GitHubCodeSearchPage(
            total_count=1 if has_skill else 0,
            incomplete_results=False,
            items=[github_code_search_item("prompt-skills")] if has_skill else [],
        )

    filters = skills.GitHubRepositoryFilters(
        all_github=True,
        repository_names=("skills",),
    )
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_repository_page", fake_search_repository_page)
        monkeypatch.setattr(client, "search_code_page", fake_search_code_page)
        repositories = [
            repository
            async for repository in client.iter_repositories(
                filters,
                stats,
                recursive=True,
                subfolder="skills",
            )
        ]

    assert [repository.repo.source for repository in repositories] == ["acme/prompt-skills"]
    assert len(repository_queries) == 1
    assert "skills" in repository_queries[0][0]
    assert "in:name" in repository_queries[0][0]
    assert code_queries == [
        ("filename:SKILL.md repo:acme/agent-skills path:skills", 1),
        ("filename:SKILL.md repo:acme/prompt-skills path:skills", 1),
    ]
    assert stats.active_repository_count == 2
    assert stats.filtered_repository_count == 1


async def test_github_repository_search_applies_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_search_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubRepositorySearchPage:
        calls.append((query, page))
        return skills.GitHubRepositorySearchPage(
            total_count=4,
            incomplete_results=False,
            items=[
                github_search_repository("blocked", owner="blocked-org"),
                github_search_repository("blocked-repo"),
                github_search_repository("sample-skills"),
                github_search_repository("kept"),
            ],
        )

    filters = skills.GitHubRepositoryFilters(
        all_github=True,
        excluded_organizations=("blocked-org",),
        excluded_repositories=("acme/blocked-repo",),
        excluded_repository_names=("skills",),
    )
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    budget = skills.GitHubSearchBudget(remaining=None)
    start = skills.parse_github_datetime("2026-01-01T00:00:00Z", upper_bound=False)
    end = skills.parse_github_datetime("2026-01-01T00:00:02Z", upper_bound=True)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_repository_page", fake_search_page)
        repositories = [
            repository
            async for repository in client._search_repository_window(
                filters,
                skills.GitHubSearchTarget(qualifier="", value=""),
                created_start=start,
                created_end=end,
                stats=stats,
                budget=budget,
            )
        ]

    assert [repository.repo.source for repository in repositories] == ["acme/kept"]
    assert "-org:blocked-org" in calls[0][0]
    assert "-repo:acme/blocked-repo" in calls[0][0]
    assert stats.filtered_repository_count == 3
    assert stats.active_repository_count == 1


async def test_github_repository_search_shards_more_than_one_thousand_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_search_page(
        query: str,
        *,
        page: int,
    ) -> skills.GitHubRepositorySearchPage:
        calls.append((query, page))
        if len(calls) == 1:
            return skills.GitHubRepositorySearchPage(
                total_count=1001,
                incomplete_results=False,
                items=[],
            )
        return skills.GitHubRepositorySearchPage(
            total_count=1,
            incomplete_results=False,
            items=[github_search_repository(f"repo-{len(calls)}")],
        )

    filters = skills.GitHubRepositoryFilters(all_github=True)
    stats = skills.GitHubDiscoveryStats(scope_label=filters.scope_label)
    budget = skills.GitHubSearchBudget(remaining=None)
    start = skills.parse_github_datetime("2026-01-01T00:00:00Z", upper_bound=False)
    end = skills.parse_github_datetime("2026-01-01T00:00:02Z", upper_bound=True)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client, "search_repository_page", fake_search_page)
        repositories = [
            repository
            async for repository in client._search_repository_window(
                filters,
                skills.GitHubSearchTarget(qualifier="", value=""),
                created_start=start,
                created_end=end,
                stats=stats,
                budget=budget,
            )
        ]

    assert [repository.repo.repo for repository in repositories] == ["repo-2", "repo-3"]
    assert len(calls) == 3
    assert "created:2026-01-01T00:00:00Z..2026-01-01T00:00:01Z" in calls[1][0]
    assert "created:2026-01-01T00:00:02Z..2026-01-01T00:00:02Z" in calls[2][0]
    assert stats.listed_repository_count == 2


async def test_github_verified_organization_lookup_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_get(url: str) -> SimpleNamespace:
        calls.append(url)
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"is_verified": True},
        )

    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        assert await client.organization_is_verified("Acme") is True
        assert await client.organization_is_verified("acme") is True

    assert calls == ["https://api.github.com/orgs/Acme"]


def github_response(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    message: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        text=message,
        json=lambda: {"message": message},
    )


def test_github_response_error_message_includes_http_diagnostics() -> None:
    response = github_response(
        502,
        headers={"x-github-request-id": "REQUEST-502"},
    )

    assert skills.github_response_error_message(response, "GitHub tree lookup failed") == (
        "GitHub tree lookup failed (HTTP 502, request ID REQUEST-502): "
        "empty response body"
    )


def test_github_rate_limit_wait_ignores_ordinary_forbidden_response() -> None:
    response = github_response(403, message="Resource not accessible by personal access token")

    assert (
        skills.github_rate_limit_wait(
            response,
            retry_attempt=0,
            now_epoch_seconds=1_000,
        )
        is None
    )


def test_github_secondary_rate_limit_uses_exponential_fallback() -> None:
    response = github_response(403, message="You have exceeded a secondary rate limit")

    first = skills.github_rate_limit_wait(
        response,
        retry_attempt=0,
        now_epoch_seconds=1_000,
    )
    second = skills.github_rate_limit_wait(
        response,
        retry_attempt=1,
        now_epoch_seconds=1_000,
    )
    capped = skills.github_rate_limit_wait(
        response,
        retry_attempt=20,
        now_epoch_seconds=1_000,
    )

    assert first == skills.GitHubRateLimitWait(seconds=60, reason="secondary")
    assert second == skills.GitHubRateLimitWait(seconds=120, reason="secondary")
    assert capped == skills.GitHubRateLimitWait(seconds=900, reason="secondary")


async def test_github_client_waits_and_retries_same_request_after_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            github_response(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": "1009",
                    "x-ratelimit-resource": "search",
                },
                message="API rate limit exceeded",
            ),
            github_response(
                429,
                headers={"retry-after": "3"},
                message="You have exceeded a secondary rate limit",
            ),
            github_response(200),
        ]
    )
    calls: list[tuple[str, dict[str, object]]] = []
    sleeps: list[float] = []

    async def fake_get(url: str, **kwargs: object) -> SimpleNamespace:
        calls.append((url, kwargs))
        return next(responses)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(skills.time, "time", lambda: 1_000)
    monkeypatch.setattr(skills.asyncio, "sleep", fake_sleep)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        response = await client._get(
            "https://api.github.com/search/repositories",
            params={"q": "is:public"},
        )

    assert response.status_code == 200
    assert calls == [
        (
            "https://api.github.com/search/repositories",
            {"params": {"q": "is:public"}},
        ),
        (
            "https://api.github.com/search/repositories",
            {"params": {"q": "is:public"}},
        ),
        (
            "https://api.github.com/search/repositories",
            {"params": {"q": "is:public"}},
        ),
    ]
    assert sleeps == [10, 4]


async def test_github_client_retries_transient_http_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            github_response(502, headers={"x-github-request-id": "REQUEST-ONE"}),
            github_response(503, headers={"x-github-request-id": "REQUEST-TWO"}),
            github_response(200),
        ]
    )
    calls = 0
    sleeps: list[float] = []

    async def fake_get(url: str, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return next(responses)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(skills.asyncio, "sleep", fake_sleep)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        response = await client._get("https://api.github.com/repos/acme/skills")

    assert response.status_code == 200
    assert calls == 3
    assert sleeps == [1, 2]


async def test_github_client_retries_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    async def fake_get(url: str, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout(
                "upstream timed out",
                request=httpx.Request("GET", url),
            )
        return github_response(200)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(skills.asyncio, "sleep", fake_sleep)
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        response = await client._get("https://api.github.com/repos/acme/skills")

    assert response.status_code == 200
    assert calls == 3
    assert sleeps == [1, 2]


async def test_github_owner_malformed_json_is_systemic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200,
            text="not-json",
            json=lambda: (_ for _ in ()).throw(ValueError("invalid JSON")),
        )

    async with skills.GitHubClient() as client:
        assert client._client.follow_redirects is True
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.GitHubSystemicError, match="malformed owner metadata JSON"):
            await client.owner("acme")


async def test_github_resolve_commit_sha_pins_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, *, params: dict[str, str]) -> SimpleNamespace:
        assert url.endswith("/repos/acme/agent-skills/commits")
        assert params == {"sha": "main", "per_page": "1"}
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: [{"sha": RESOLVED_COMMIT_SHA.upper()}],
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        resolved = await client.resolve_commit_sha(repo, "main")

    assert resolved == RESOLVED_COMMIT_SHA


async def test_github_resolve_commit_sha_classifies_empty_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, *, params: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(status_code=409, text="Git Repository is empty.")

    repo = skills.parse_github_repository_url("https://github.com/acme/empty")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillNotFoundError, match="has no commits"):
            await client.resolve_commit_sha(repo, "main")


async def test_github_recursive_tree_rejects_wrong_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, *, params: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"truncated": False, "tree": [{"path": "SKILL.md"}]},
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.GitHubSystemicError, match="invalid item"):
            await client.recursive_tree(repo, RESOLVED_COMMIT_SHA)


async def test_github_recursive_tree_classifies_truncated_response_as_skippable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, *, params: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"truncated": True, "tree": []},
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/large-repository")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(
            skills.GitHubTreeTruncatedError,
            match="repository scan skipped",
        ):
            await client.recursive_tree(repo, RESOLVED_COMMIT_SHA)


def test_discover_skill_paths_uses_exact_skill_subfolder() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/nested/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, recursive=False, subfolder="skills") == [
        "skills/SKILL.md"
    ]


def test_discover_skill_paths_recurses_under_subfolder_when_requested() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/docs/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="examples/demo/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, recursive=True, subfolder="skills") == [
        "skills/SKILL.md",
        "skills/docs/SKILL.md",
        "skills/weather/SKILL.md",
    ]


def test_discover_skill_paths_does_not_recurse_under_subfolder_by_default() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/docs/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="examples/demo/SKILL.md", type="blob", size=50),
    ]

    with pytest.raises(skills.SkillNotFoundError, match="No SKILL.md found in GitHub subfolder"):
        skills.discover_skill_paths(tree, recursive=False, subfolder="skills")


def test_discover_skill_paths_only_uses_repository_root_without_subfolder() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, recursive=False, subfolder="") == ["SKILL.md"]


def test_discover_skill_paths_recurses_from_repository_root_when_requested() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, recursive=True, subfolder="") == [
        "SKILL.md",
        "skills/SKILL.md",
        "skills/weather/SKILL.md",
    ]


def test_discover_skill_paths_does_not_recurse_from_repository_root() -> None:
    tree = [
        skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
    ]

    with pytest.raises(skills.SkillNotFoundError, match="repository root"):
        skills.discover_skill_paths(tree, recursive=False, subfolder="")


def test_skill_bundle_tree_items_uses_nearest_skill_root() -> None:
    tree = [
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob"),
        skills.GitHubTreeItem(path="skills/weather/README.md", type="blob"),
        skills.GitHubTreeItem(
            path="skills/weather/scripts/run.sh",
            type="blob",
            mode="100755",
        ),
        skills.GitHubTreeItem(path="skills/weather/assets/logo.png", type="blob"),
        skills.GitHubTreeItem(path="skills/weather/nested/SKILL.md", type="blob"),
        skills.GitHubTreeItem(path="skills/weather/nested/reference.md", type="blob"),
        skills.GitHubTreeItem(
            path="skills/weather/node_modules/package/index.js",
            type="blob",
        ),
        skills.GitHubTreeItem(
            path="skills/weather/current",
            type="blob",
            mode="120000",
        ),
        skills.GitHubTreeItem(path="skills/weather/vendor-repo", type="commit"),
    ]

    parent_items = skills.skill_bundle_tree_items(
        tree,
        skill_path="skills/weather/SKILL.md",
    )
    nested_items = skills.skill_bundle_tree_items(
        tree,
        skill_path="skills/weather/nested/SKILL.md",
    )

    assert [item.path for item in parent_items] == [
        "skills/weather/SKILL.md",
        "skills/weather/README.md",
        "skills/weather/assets/logo.png",
        "skills/weather/scripts/run.sh",
    ]
    assert [item.path for item in nested_items] == [
        "skills/weather/nested/SKILL.md",
        "skills/weather/nested/reference.md",
    ]


def test_skill_bundle_tree_items_allows_build_skill_root() -> None:
    tree = [
        skills.GitHubTreeItem(path="build/agp/agp-9-upgrade/SKILL.md", type="blob"),
        skills.GitHubTreeItem(path="build/agp/agp-9-upgrade/references/guide.md", type="blob"),
        skills.GitHubTreeItem(
            path="build/agp/agp-9-upgrade/node_modules/package/index.js",
            type="blob",
        ),
    ]

    items = skills.skill_bundle_tree_items(
        tree,
        skill_path="build/agp/agp-9-upgrade/SKILL.md",
    )

    assert [item.path for item in items] == [
        "build/agp/agp-9-upgrade/SKILL.md",
        "build/agp/agp-9-upgrade/references/guide.md",
    ]


async def test_fetch_skill_bundle_preserves_text_binary_and_executable_files() -> None:
    class FakeGitHubClient:
        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            assert path == "skills/weather/SKILL.md"
            return "---\nname: Weather\ndescription: Weather APIs.\n---\n\n# Weather\n"

        async def raw_file_bytes(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> bytes:
            return {
                "skills/weather/assets/logo.bin": b"\x00\xff",
                "skills/weather/references/guide.md": b"# Guide\n",
                "skills/weather/scripts/run.sh": b"#!/bin/sh\necho weather\n",
            }[path]

    tree = [
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=65),
        skills.GitHubTreeItem(
            path="skills/weather/scripts/run.sh",
            type="blob",
            size=23,
            mode="100755",
        ),
        skills.GitHubTreeItem(
            path="skills/weather/assets/logo.bin",
            type="blob",
            size=2,
        ),
        skills.GitHubTreeItem(
            path="skills/weather/references/guide.md",
            type="blob",
            size=8,
        ),
    ]
    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")

    skill_md, files, bundle_size = await skills.fetch_skill_bundle(
        client=FakeGitHubClient(),  # type: ignore[arg-type]
        repo=repo,
        ref="main",
        tree=tree,
        skill_path="skills/weather/SKILL.md",
    )

    assert skill_md.startswith("---\nname: Weather")
    assert files == [
        {"path": "SKILL.md", "contents": skill_md},
        {"path": "assets/logo.bin", "contents": "AP8=", "encoding": "base64"},
        {"path": "references/guide.md", "contents": "# Guide\n"},
        {
            "path": "scripts/run.sh",
            "contents": "#!/bin/sh\necho weather\n",
            "executable": True,
        },
    ]
    assert bundle_size == len(skill_md.encode()) + 2 + 8 + 23
    assert skills.content_hash(files) != skills.content_hash(
        [file for file in files if file["path"] != "scripts/run.sh"]
    )


def test_skill_bundle_tree_items_rejects_oversized_file_count() -> None:
    tree = [skills.GitHubTreeItem(path="skill/SKILL.md", type="blob")]
    tree.extend(
        skills.GitHubTreeItem(path=f"skill/references/{index}.md", type="blob")
        for index in range(skills.MAX_SKILL_BUNDLE_FILES)
    )

    with pytest.raises(skills.InvalidSkillBundleError, match="exceeds 256 files"):
        skills.skill_bundle_tree_items(tree, skill_path="skill/SKILL.md")


def test_checked_github_import_size_enforces_aggregate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(skills, "MAX_GITHUB_IMPORT_BYTES", 10)

    assert skills.checked_github_import_size(4, 6) == 10
    with pytest.raises(skills.SkillCliError, match="narrower --subfolder"):
        skills.checked_github_import_size(4, 7)


async def test_fetch_skill_bundle_checks_actual_bundle_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        async def raw_file(self, *args: object) -> str:
            return "# root\n"

        async def raw_file_bytes(self, *args: object) -> bytes:
            return b"123456789"

    monkeypatch.setattr(skills, "MAX_SKILL_BUNDLE_BYTES", 15)
    tree = [
        skills.GitHubTreeItem(path="skill/SKILL.md", type="blob"),
        skills.GitHubTreeItem(path="skill/reference.txt", type="blob"),
    ]
    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")

    with pytest.raises(skills.InvalidSkillBundleError, match="exceeds 15 bytes"):
        await skills.fetch_skill_bundle(
            client=FakeGitHubClient(),  # type: ignore[arg-type]
            repo=repo,
            ref="main",
            tree=tree,
            skill_path="skill/SKILL.md",
        )


def test_skill_bundle_tree_items_rejects_unsafe_paths() -> None:
    tree = [
        skills.GitHubTreeItem(path="skill/SKILL.md", type="blob"),
        skills.GitHubTreeItem(path="skill/../escape.txt", type="blob"),
    ]

    with pytest.raises(skills.InvalidSkillBundleError, match="normalized relative POSIX"):
        skills.skill_bundle_tree_items(tree, skill_path="skill/SKILL.md")


def test_skill_slug_root_is_relative_to_import_subfolder() -> None:
    assert skills.skill_slug_root("skills/algorithmic-art", "skills") == "algorithmic-art"


def test_github_import_text_formatter_outputs_compact_tsv() -> None:
    record = logging.LogRecord(
        name=skills.logger.name,
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="github request rate limited; waiting before retry",
        args=(),
        exc_info=None,
    )
    record.created = datetime(2026, 7, 18, 19, 31, 7).timestamp()
    record.msecs = 889

    assert skills.GitHubImportTextFormatter().format(record) == (
        "2026-07-18 19:31:07,889\t"
        "WARNING\t"
        "github request rate limited; waiting before retry"
    )

    saved_record = logging.LogRecord(
        name=skills.logger.name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="github skill import saved skill",
        args=(),
        exc_info=None,
    )
    saved_record.created = datetime(2026, 7, 18, 19, 32, 6).timestamp()
    saved_record.msecs = 381
    saved_record.source = "android/skills"
    saved_record.skill_id = "android/skills/camera-camerax"

    assert skills.GitHubImportTextFormatter().format(saved_record) == (
        "2026-07-18 19:32:06,381\t"
        "INFO\t"
        "github skill import saved skill\t"
        "android/skills\t"
        "android/skills/camera-camerax"
    )


def test_configure_github_import_text_output_formats_root_and_suppresses_httpx_info() -> None:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_root_level = root_logger.level
    original_skills_handlers = skills.logger.handlers[:]
    original_skills_propagate = skills.logger.propagate
    original_skills_level = skills.logger.level
    httpx_logger = logging.getLogger("httpx")
    original_httpx_level = httpx_logger.level

    try:
        skills.configure_github_import_output("text")

        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0].formatter, skills.GitHubImportTextFormatter)
        assert skills.logger.handlers == []
        assert skills.logger.propagate is True
        assert httpx_logger.level == logging.WARNING
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_root_level)
        skills.logger.handlers.clear()
        skills.logger.handlers.extend(original_skills_handlers)
        skills.logger.propagate = original_skills_propagate
        skills.logger.setLevel(original_skills_level)
        httpx_logger.setLevel(original_httpx_level)


def test_manage_dispatches_skills_add(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {}
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("---\nname: Weather\n---\n", encoding="utf-8")

    async def fake_add_skill_from_args(args) -> int:
        called["source"] = args.source
        called["skill_file"] = args.skill_file
        return 0

    monkeypatch.setattr(manage, "add_skill_from_args", fake_add_skill_from_args)

    result = manage.main(
        [
            "skills",
            "add",
            "--source",
            "acme/agent-skills",
            "--skill-file",
            str(skill_file),
        ]
    )

    assert result == 0
    assert called == {"source": "acme/agent-skills", "skill_file": str(skill_file)}


def test_manage_dispatches_skills_import_github(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    async def fake_import_github_from_args(args) -> int:
        called["owner"] = args.owner
        called["subfolder"] = args.subfolder
        return 0

    monkeypatch.setattr(manage, "import_github_from_args", fake_import_github_from_args)

    result = manage.main(
        [
            "skills",
            "import-github",
            "acme",
            "--subfolder",
            "skills",
        ]
    )

    assert result == 0
    assert called == {
        "owner": "acme",
        "subfolder": "skills",
    }


def test_manage_parses_filtered_multi_target_github_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_import_github_from_args(args: Namespace) -> int:
        called.update(vars(args))
        return 0

    monkeypatch.setattr(manage, "import_github_from_args", fake_import_github_from_args)

    result = manage.main(
        [
            "skills",
            "import-github",
            "--org",
            "anthropics",
            "--org",
            "openai",
            "--repo",
            "github/awesome-copilot",
            "--min-stars",
            "100",
            "--active-within-days",
            "90",
            "--language",
            "Python",
            "--repo-name",
            "skills",
            "--output",
            "text",
            "--exclude-org",
            "bad-org",
            "--exclude-user",
            "bad-user",
            "--exclude-repo",
            "bad-org/bad-skills",
            "--exclude-repo-name",
            "sample",
            "--topic",
            "agents",
            "--verified-orgs-only",
            "--max-repositories",
            "500",
        ]
    )

    assert result == 0
    assert called["owner"] is None
    assert called["organizations"] == ["anthropics", "openai"]
    assert called["repositories"] == ["github/awesome-copilot"]
    assert called["min_stars"] == 100
    assert called["active_within_days"] == 90
    assert called["language"] == "Python"
    assert called["repository_names"] == ["skills"]
    assert called["output"] == "text"
    assert called["excluded_organizations"] == ["bad-org"]
    assert called["excluded_users"] == ["bad-user"]
    assert called["excluded_repositories"] == ["bad-org/bad-skills"]
    assert called["excluded_repository_names"] == ["sample"]
    assert called["topics"] == ["agents"]
    assert called["verified_orgs_only"] is True
    assert called["max_repositories"] == 500


def test_github_import_filters_require_target_and_validate_ranges() -> None:
    with pytest.raises(skills.SkillCliError, match="choose a GitHub target"):
        skills.github_repository_filters_from_args(Namespace())

    args = github_import_args()
    args.min_stars = 20
    args.max_stars = 10
    with pytest.raises(skills.SkillCliError, match="min-stars"):
        skills.github_repository_filters_from_args(args)


def test_manage_import_github_rejects_missing_or_conflicting_targets() -> None:
    with pytest.raises(SystemExit):
        manage.main(["skills", "import-github"])
    with pytest.raises(SystemExit):
        manage.main(
            ["skills", "import-github", "--all-github", "--org", "anthropics"]
        )


@pytest.mark.parametrize(
    "owner",
    ["https://github.com/acme", "acme/agent-skills", "-acme", "acme--labs"],
)
def test_manage_import_github_rejects_non_owner_input(owner: str) -> None:
    with pytest.raises(SystemExit):
        manage.main(
            [
                "skills",
                "import-github",
                owner,
                "--subfolder",
                "skills",
            ]
        )


def test_manage_import_github_scans_repository_root_when_subfolder_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_import_github_from_args(args: Namespace) -> int:
        called["owner"] = args.owner
        called["subfolder"] = args.subfolder
        return 0

    monkeypatch.setattr(manage, "import_github_from_args", fake_import_github_from_args)

    assert manage.main(["skills", "import-github", "acme"]) == 0
    assert called == {"owner": "acme", "subfolder": None}


@pytest.mark.parametrize("subfolder", ["/skills", "skills/", "../skills", "skills//nested"])
def test_import_github_parsers_reject_unsafe_subfolder(subfolder: str) -> None:
    with pytest.raises(SystemExit):
        manage.main(
            ["skills", "import-github", "acme", "--subfolder", subfolder]
        )
    with pytest.raises(SystemExit):
        skills.main(["import-github", "acme", "--subfolder", subfolder])


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--ref", "main"),
        ("--slug", "weather"),
        ("--name", "Weather"),
        ("--description", "Weather APIs"),
        ("--install-url", "https://example.com/install"),
        ("--website-url", "https://example.com"),
    ],
)
def test_import_github_parsers_reject_repository_specific_flags(
    flag: str,
    value: str,
) -> None:
    args = ["import-github", "acme", "--subfolder", "skills", flag, value]
    with pytest.raises(SystemExit):
        skills.main(args)
    with pytest.raises(SystemExit):
        manage.main(["skills", *args])


def test_manage_import_github_rejects_removed_curated_flag() -> None:
    with pytest.raises(SystemExit):
        manage.main(
            [
                "skills",
                "import-github",
                "acme",
                "--subfolder",
                "skills",
                "--curated",
            ]
        )


def test_manage_dispatches_skills_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    async def fake_refresh_github_from_args(args: Namespace) -> int:
        called["github_token"] = args.github_token
        called["timeout_seconds"] = args.timeout_seconds
        return 0

    monkeypatch.setattr(manage, "refresh_github_from_args", fake_refresh_github_from_args)

    result = manage.main(
        [
            "skills",
            "refresh",
            "--github-token",
            "github-token",
            "--timeout-seconds",
            "3",
        ]
    )

    assert result == 0
    assert called == {"github_token": "github-token", "timeout_seconds": 3.0}


def test_github_token_from_args_prefers_nonempty_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(skills.GITHUB_TOKEN_ENV, "environment-token")

    assert skills.github_token_from_args(Namespace(github_token=" explicit-token ")) == (
        "explicit-token"
    )
    assert skills.github_token_from_args(Namespace(github_token="  ")) == "environment-token"


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
def test_github_http_error_classifies_systemic_failures(status_code: int) -> None:
    error = skills.github_http_error(status_code, "GitHub request failed")

    assert isinstance(error, skills.GitHubSystemicError)


@pytest.mark.parametrize("status_code", [400, 409, 422])
def test_github_http_error_keeps_source_failures_isolated(status_code: int) -> None:
    error = skills.github_http_error(status_code, "GitHub request failed")

    assert isinstance(error, skills.SkillCliError)
    assert not isinstance(error, skills.GitHubSystemicError)


async def test_refresh_github_groups_repository_reads_and_refreshes_exact_targets(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [
        refresh_target("one", "skills/one"),
        refresh_target("two", "skills/two", ref="stable"),
    ]
    calls = {"metadata": 0, "resolve": 0, "tree": 0}
    requested_refs: list[str] = []
    fetched_skill_paths: list[str] = []

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            assert token == "environment-token"
            assert timeout_seconds == 3.0

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            calls["metadata"] += 1
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            calls["resolve"] += 1
            requested_refs.append(ref)
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            calls["tree"] += 1
            assert ref == RESOLVED_COMMIT_SHA
            return [
                skills.GitHubTreeItem(path="skills/one/SKILL.md", type="blob"),
                skills.GitHubTreeItem(
                    path="skills/one/scripts/run.sh",
                    type="blob",
                    mode="100755",
                ),
                skills.GitHubTreeItem(path="skills/two/SKILL.md", type="blob"),
                skills.GitHubTreeItem(path="skills/new/SKILL.md", type="blob"),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            fetched_skill_paths.append(path)
            return f"---\nname: {Path(path).parent.name}\ndescription: refreshed\n---\n"

        async def raw_file_bytes(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> bytes:
            assert path == "skills/one/scripts/run.sh"
            return b"#!/bin/sh\necho refreshed\n"

    saved: list[tuple[str, list[skills.SkillSnapshotFile]]] = []

    async def fake_load_targets():
        return targets, []

    async def fake_save(
        target: skills.SkillRefreshTarget,
        *,
        skill_md: str,
        files: list[skills.SkillSnapshotFile],
    ) -> tuple[str, bool]:
        saved.append((target.slug, files))
        return f"hash-{target.slug}", target.slug == "one"

    monkeypatch.setenv(skills.GITHUB_TOKEN_ENV, "environment-token")
    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "load_skill_refresh_targets", fake_load_targets)
    monkeypatch.setattr(skills, "save_refreshed_skill", fake_save)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.refresh_github_from_args(
        Namespace(github_token="", timeout_seconds=3.0)
    )

    assert result == 0
    assert calls == {"metadata": 1, "resolve": 2, "tree": 2}
    assert requested_refs == ["main", "stable"]
    assert fetched_skill_paths == ["skills/one/SKILL.md", "skills/two/SKILL.md"]
    assert [slug for slug, _files in saved] == ["one", "two"]
    assert saved[0][1][1] == {
        "path": "scripts/run.sh",
        "contents": "#!/bin/sh\necho refreshed\n",
        "executable": True,
    }
    assert capsys.readouterr().out.strip() == (
        "refreshed 2 of 2 GitHub skill(s): 1 updated, 1 unchanged, 0 failed"
    )
    start_record = next(
        record
        for record in caplog.records
        if record.message == "github skills refresh started"
    )
    assert start_record.github_token_configured is True
    assert not hasattr(start_record, "github_token")


async def test_refresh_github_does_not_substitute_nested_skill_for_missing_root(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [
        refresh_target("outer", "skills/outer"),
        refresh_target("valid", "skills/valid"),
    ]

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            return [
                skills.GitHubTreeItem(
                    path="skills/outer/nested/SKILL.md",
                    type="blob",
                ),
                skills.GitHubTreeItem(path="skills/valid/SKILL.md", type="blob"),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            assert path == "skills/valid/SKILL.md"
            return "---\nname: valid\ndescription: valid\n---\n"

    saved: list[str] = []

    async def fake_load_targets():
        return targets, []

    async def fake_save(
        target: skills.SkillRefreshTarget,
        *,
        skill_md: str,
        files: list[skills.SkillSnapshotFile],
    ) -> tuple[str, bool]:
        saved.append(target.slug)
        return "valid-hash", True

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "load_skill_refresh_targets", fake_load_targets)
    monkeypatch.setattr(skills, "save_refreshed_skill", fake_save)

    result = await skills.refresh_github_from_args(
        Namespace(github_token="", timeout_seconds=3.0)
    )

    assert result == 1
    assert saved == ["valid"]
    assert capsys.readouterr().out.strip() == (
        "refreshed 1 of 2 GitHub skill(s): 1 updated, 0 unchanged, 1 failed"
    )


async def test_refresh_github_aborts_on_systemic_github_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [
        refresh_target("one", "skills/one"),
        refresh_target("two", "skills/two", source="other/agent-skills"),
    ]
    metadata_calls = 0

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            nonlocal metadata_calls
            metadata_calls += 1
            raise skills.GitHubSystemicError("GitHub server unavailable")

    async def fake_load_targets():
        return targets, []

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "load_skill_refresh_targets", fake_load_targets)

    result = await skills.refresh_github_from_args(
        Namespace(github_token="", timeout_seconds=3.0)
    )

    assert result == 1
    assert metadata_calls == 1
    assert capsys.readouterr().out.strip() == (
        "refreshed 0 of 2 GitHub skill(s): 0 updated, 0 unchanged, 2 failed"
    )


async def test_refresh_github_with_no_skills_is_successful_noop(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load_targets():
        return [], []

    def fail_if_client_is_created(*args: object, **kwargs: object) -> None:
        raise AssertionError("GitHub client should not open when no skills are eligible")

    monkeypatch.setattr(skills, "load_skill_refresh_targets", fake_load_targets)
    monkeypatch.setattr(skills, "GitHubClient", fail_if_client_is_created)

    result = await skills.refresh_github_from_args(
        Namespace(github_token="", timeout_seconds=3.0)
    )

    assert result == 0
    assert capsys.readouterr().out.strip() == (
        "refreshed 0 of 0 GitHub skill(s): 0 updated, 0 unchanged, 0 failed"
    )


async def test_refresh_existing_skill_snapshot_preserves_catalog_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = refresh_target("weather", "skills/weather")
    skill = SimpleNamespace(
        id=target.skill_id,
        current_snapshot_id=target.current_snapshot_id,
        source_type="github",
        status="active",
        source=target.source,
        slug=target.slug,
        repository=target.repository,
        name="Curated weather",
        description="Curated description",
        visibility="unlisted",
        installs=42,
        is_duplicate=True,
        owner_user_id="owner-id",
        install_url="https://docs.example/weather",
    )
    current_snapshot = SimpleNamespace(
        id=target.current_snapshot_id,
        skill_id=target.skill_id,
        status="active",
        is_latest=True,
        content_hash=target.current_hash,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.execute_count = 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.execute_count += 1
            selected = skill if self.execute_count == 1 else current_snapshot
            return SimpleNamespace(scalar_one_or_none=lambda: selected)

    async def fake_upsert(
        session: object,
        selected_skill: object,
        *,
        skill_md: str,
        files: list[skills.SkillSnapshotFile],
    ) -> SimpleNamespace:
        assert selected_skill is skill
        skill.current_snapshot_id = "new-snapshot-id"
        return SimpleNamespace(content_hash="new-hash")

    monkeypatch.setattr(skills, "upsert_skill_snapshot", fake_upsert)
    files: list[skills.SkillSnapshotFile] = [
        {"path": "SKILL.md", "contents": "# Refreshed weather"}
    ]

    snapshot_hash, changed = await skills.refresh_existing_skill_snapshot(
        FakeSession(),  # type: ignore[arg-type]
        target,
        skill_md="# Refreshed weather",
        files=files,
    )

    assert (snapshot_hash, changed) == ("new-hash", True)
    assert skill.current_snapshot_id == "new-snapshot-id"
    assert skill.name == "Curated weather"
    assert skill.description == "Curated description"
    assert skill.visibility == "unlisted"
    assert skill.installs == 42
    assert skill.is_duplicate is True
    assert skill.owner_user_id == "owner-id"
    assert skill.install_url == "https://docs.example/weather"


async def test_refresh_existing_skill_snapshot_skips_unchanged_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files: list[skills.SkillSnapshotFile] = [
        {"path": "SKILL.md", "contents": "# Unchanged"}
    ]
    target = refresh_target(
        "weather",
        "skills/weather",
        current_hash=skills.content_hash(files),
    )
    skill = SimpleNamespace(
        id=target.skill_id,
        current_snapshot_id=target.current_snapshot_id,
        source_type="github",
        status="active",
        source=target.source,
        slug=target.slug,
        repository=target.repository,
    )
    current_snapshot = SimpleNamespace(
        id=target.current_snapshot_id,
        skill_id=target.skill_id,
        status="active",
        is_latest=True,
        content_hash=target.current_hash,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.execute_count = 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.execute_count += 1
            selected = skill if self.execute_count == 1 else current_snapshot
            return SimpleNamespace(scalar_one_or_none=lambda: selected)

    async def fail_if_upserted(*args: object, **kwargs: object) -> None:
        raise AssertionError("unchanged snapshot should not be rewritten")

    monkeypatch.setattr(skills, "upsert_skill_snapshot", fail_if_upserted)

    result = await skills.refresh_existing_skill_snapshot(
        FakeSession(),  # type: ignore[arg-type]
        target,
        skill_md="# Unchanged",
        files=files,
    )

    assert result == (target.current_hash, False)


async def test_refresh_existing_skill_snapshot_revalidates_snapshot_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = refresh_target("weather", "skills/weather")
    skill = SimpleNamespace(
        id=target.skill_id,
        current_snapshot_id=target.current_snapshot_id,
        source_type="github",
        status="active",
        source=target.source,
        slug=target.slug,
        repository=target.repository,
    )
    quarantined_snapshot = SimpleNamespace(
        id=target.current_snapshot_id,
        skill_id=target.skill_id,
        status="quarantined",
        is_latest=True,
        content_hash=target.current_hash,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.execute_count = 0

        async def execute(self, statement: object) -> SimpleNamespace:
            self.execute_count += 1
            selected = skill if self.execute_count == 1 else quarantined_snapshot
            return SimpleNamespace(scalar_one_or_none=lambda: selected)

    async def fail_if_upserted(*args: object, **kwargs: object) -> None:
        raise AssertionError("quarantined snapshot should not be refreshed")

    monkeypatch.setattr(skills, "upsert_skill_snapshot", fail_if_upserted)

    with pytest.raises(skills.SkillCliError, match="snapshot changed"):
        await skills.refresh_existing_skill_snapshot(
            FakeSession(),  # type: ignore[arg-type]
            target,
            skill_md="# Refreshed",
            files=[{"path": "SKILL.md", "contents": "# Refreshed"}],
        )


async def test_upsert_skill_snapshot_locks_skill_before_snapshot_flags() -> None:
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="old-snapshot-id")
    snapshot = SimpleNamespace(
        id="snapshot-id",
        content_hash="",
        skill_md="",
        metadata_={},
        files=[],
        status="inactive",
        is_latest=False,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(str(statement))
            if len(self.statements) == 3:
                return SimpleNamespace(scalar_one_or_none=lambda: snapshot)
            return SimpleNamespace()

    session = FakeSession()
    files: list[skills.SkillSnapshotFile] = [
        {"path": "SKILL.md", "contents": "# Refreshed"}
    ]

    result = await skills.upsert_skill_snapshot(
        session,  # type: ignore[arg-type]
        skill,  # type: ignore[arg-type]
        skill_md="# Refreshed",
        files=files,
    )

    assert result is snapshot
    assert "FOR UPDATE" in session.statements[0]
    assert session.statements[1].startswith("UPDATE skill_snapshots")
    assert session.statements[3].startswith("DELETE FROM skill_audits")
    assert skill.current_snapshot_id == "snapshot-id"
    assert snapshot.is_latest is True


async def test_upsert_skill_snapshot_refuses_quarantined_content() -> None:
    skill = SimpleNamespace(id="skill-id", current_snapshot_id="old-snapshot-id")
    snapshot = SimpleNamespace(
        id="snapshot-id",
        content_hash="",
        skill_md="# Unsafe",
        metadata_={},
        files=[],
        status="quarantined",
        is_latest=False,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object) -> SimpleNamespace:
            self.statements.append(str(statement))
            if len(self.statements) == 3:
                return SimpleNamespace(scalar_one_or_none=lambda: snapshot)
            return SimpleNamespace()

    session = FakeSession()
    files: list[skills.SkillSnapshotFile] = [
        {"path": "SKILL.md", "contents": "# Refreshed"}
    ]

    with pytest.raises(skills.SkillCliError, match="quarantined"):
        await skills.upsert_skill_snapshot(
            session,  # type: ignore[arg-type]
            skill,  # type: ignore[arg-type]
            skill_md="# Refreshed",
            files=files,
        )

    assert "FOR UPDATE" in session.statements[0]
    assert skill.current_snapshot_id == "old-snapshot-id"
    assert snapshot.status == "quarantined"
    assert snapshot.is_latest is False


async def test_import_github_logs_progress(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            assert token == "github-token"
            assert timeout_seconds == 3.0

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            assert owner == "acme"
            return repository_listing(import_repository("agent-skills"))

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            assert repo.source == "acme/agent-skills"
            return skills.GitHubRepositoryMetadata(
                default_branch="main",
                owner_avatar_url="https://avatars.example/acme.png",
            )

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            assert ref == "main"
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            assert repo.source == "acme/agent-skills"
            assert ref == RESOLVED_COMMIT_SHA
            return [
                skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob"),
                skills.GitHubTreeItem(
                    path="skills/weather/scripts/weather.sh",
                    type="blob",
                    mode="100755",
                ),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            assert repo.source == "acme/agent-skills"
            assert ref == RESOLVED_COMMIT_SHA
            assert path == "skills/weather/SKILL.md"
            return "---\nname: Weather Skill\ndescription: Weather APIs.\n---\n"

        async def raw_file_bytes(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> bytes:
            assert ref == RESOLVED_COMMIT_SHA
            assert path == "skills/weather/scripts/weather.sh"
            return b"#!/bin/sh\necho weather\n"

    class FakeSessionContext:
        async def __aenter__(self) -> "FakeSessionContext":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    async def fake_add_skill(
        session: object,
        payload: skills.SkillAddInput,
        *,
        preserve_catalog_state: bool,
    ):
        assert preserve_catalog_state is True
        assert payload.source == "acme/agent-skills"
        assert payload.repository_subfolder == "skills/weather"
        assert payload.files == [
            {"path": "SKILL.md", "contents": payload.skill_md},
            {
                "path": "scripts/weather.sh",
                "contents": "#!/bin/sh\necho weather\n",
                "executable": True,
            },
        ]
        return (
            SimpleNamespace(source=payload.source, slug=payload.slug),
            SimpleNamespace(content_hash="sha256:abc123"),
        )

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(skills, "add_skill", fake_add_skill)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(
        github_import_args(subfolder="skills/weather")
    )

    assert result == 0
    records = [record for record in caplog.records if record.name == skills.logger.name]
    assert [record.message for record in records] == [
        "github skills import started",
        "github skills import repositories listed",
        "github skills import repository resolved",
        "github skills import discovered skills",
        "github skill import fetched skill file",
        "github skill import saved skill",
        "github skills import completed",
    ]
    start_record = records[0]
    assert start_record.requested_owner == "acme"
    assert start_record.github_token_configured is True
    assert not hasattr(start_record, "github_token")
    discovered_record = records[3]
    assert discovered_record.skill_count == 1
    assert discovered_record.skill_paths == ["skills/weather/SKILL.md"]
    assert records[4].skill_file_count == 2
    saved_record = records[5]
    assert saved_record.skill_id == "acme/agent-skills/weather"
    assert saved_record.source_path == "skills/weather/SKILL.md"
    assert records[6].skill_count == 1
    assert records[6].active_repository_count == 1
    assert records[6].imported_repository_count == 1


async def test_imported_skill_slug_is_stable_across_frontmatter_changes() -> None:
    repo = skills.GitHubRepository(
        owner="acme",
        repo="agent-skills",
        url="https://github.com/acme/agent-skills",
    )
    tree = [skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob")]

    class FakeGitHubClient:
        name = "Old Weather Name"

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            return f"---\nname: {self.name}\n---\n"

    client = FakeGitHubClient()
    first = await skills.import_skill_from_github_path(
        client=client,  # type: ignore[arg-type]
        repo=repo,
        ref="main",
        tree=tree,
        skill_path="skills/weather/SKILL.md",
        fetch_ref=RESOLVED_COMMIT_SHA,
        owner_avatar_url="",
        import_subfolder="skills",
    )
    client.name = "Renamed Weather Skill"
    second = await skills.import_skill_from_github_path(
        client=client,  # type: ignore[arg-type]
        repo=repo,
        ref="main",
        tree=tree + [skills.GitHubTreeItem(path="skills/other/SKILL.md", type="blob")],
        skill_path="skills/weather/SKILL.md",
        fetch_ref=RESOLVED_COMMIT_SHA,
        owner_avatar_url="",
        import_subfolder="skills",
    )

    assert first.payload.slug == "weather"
    assert second.payload.slug == "weather"
    assert first.payload.name == "Old Weather Name"
    assert second.payload.name == "Renamed Weather Skill"

    special_path = "skills/my #skill/SKILL.md"
    special = await skills.import_skill_from_github_path(
        client=client,  # type: ignore[arg-type]
        repo=repo,
        ref="main",
        tree=[skills.GitHubTreeItem(path=special_path, type="blob")],
        skill_path=special_path,
        fetch_ref=RESOLVED_COMMIT_SHA,
        owner_avatar_url="",
        import_subfolder="skills",
    )
    assert special.payload.install_url.endswith("/skills/my%20%23skill")


async def test_import_github_scans_same_subfolder_across_repositories(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_refs = {
        "alpha": "a" * 40,
        "empty": "b" * 40,
        "gamma": "c" * 40,
    }
    requested_refs: list[tuple[str, str]] = []

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(
                import_repository("alpha", default_branch="stable"),
                import_repository("empty", default_branch="main"),
                import_repository("gamma", default_branch="trunk"),
                listed_count=7,
            )

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            branches = {"alpha": "stable", "empty": "main", "gamma": "trunk"}
            return skills.GitHubRepositoryMetadata(
                default_branch=branches[repo.repo],
                owner_avatar_url="",
            )

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            requested_refs.append((repo.repo, ref))
            if repo.repo == "empty":
                raise skills.SkillNotFoundError("GitHub repository has no commits: acme/empty")
            return resolved_refs[repo.repo]

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            assert ref == resolved_refs[repo.repo]
            return [skills.GitHubTreeItem(path="skills/shared/SKILL.md", type="blob")]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            assert ref == resolved_refs[repo.repo]
            assert path == "skills/shared/SKILL.md"
            return "---\nname: Shared\ndescription: Shared workflow.\n---\n"

    commits = 0
    saved_payloads: list[skills.SkillAddInput] = []

    class FakeSessionContext:
        async def __aenter__(self) -> "FakeSessionContext":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            nonlocal commits
            commits += 1

    async def fake_add_skill(
        session: object,
        payload: skills.SkillAddInput,
        *,
        preserve_catalog_state: bool,
    ):
        assert preserve_catalog_state is True
        saved_payloads.append(payload)
        return (
            SimpleNamespace(source=payload.source, slug=payload.slug),
            SimpleNamespace(content_hash=f"hash-{payload.source_name}"),
        )

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(skills, "add_skill", fake_add_skill)

    result = await skills.import_github_from_args(
        github_import_args(subfolder="skills/shared")
    )

    assert result == 0
    assert requested_refs == [
        ("alpha", "stable"),
        ("empty", "main"),
        ("gamma", "trunk"),
    ]
    assert commits == 2
    assert [payload.source for payload in saved_payloads] == ["acme/alpha", "acme/gamma"]
    assert [payload.repository_ref for payload in saved_payloads] == ["stable", "trunk"]
    assert {payload.slug for payload in saved_payloads} == {"shared"}
    assert all(payload.repository_subfolder == "skills/shared" for payload in saved_payloads)
    assert capsys.readouterr().out.strip() == (
        "imported 2 skill(s) from 2 of 3 active GitHub repositories for acme: "
        "1 repositories skipped, 0 failed, 0 skills failed"
    )


async def test_import_github_preflights_aggregate_bundle_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(import_repository("large"))

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            return [
                skills.GitHubTreeItem(path="skills/SKILL.md", type="blob", size=11),
                skills.GitHubTreeItem(path="skills/nested/SKILL.md", type="blob", size=6),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            raise AssertionError("bundle bytes should be checked before downloads")

    def fail_if_database_opens() -> None:
        raise AssertionError("oversized repository should not open a database transaction")

    monkeypatch.setattr(skills, "MAX_GITHUB_IMPORT_BYTES", 10)
    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", fail_if_database_opens)

    result = await skills.import_github_from_args(github_import_args())

    assert result == 1


async def test_import_github_continues_after_repository_specific_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(
                import_repository("broken"),
                import_repository("working"),
            )

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            calls.append(repo.repo)
            if repo.repo == "broken":
                raise skills.SkillCliError("GitHub ref not found")
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            return [skills.GitHubTreeItem(path="skills/working/SKILL.md", type="blob")]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            return "---\nname: Working\n---\n"

    saved_sources: list[str] = []

    async def fake_save(
        imported: list[skills.ImportedSkill],
    ) -> list[tuple[SimpleNamespace, SimpleNamespace, str]]:
        item = imported[0]
        saved_sources.append(item.payload.source)
        return [
            (
                SimpleNamespace(source=item.payload.source, slug=item.payload.slug),
                SimpleNamespace(content_hash="hash-working"),
                item.source_path,
            )
        ]

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "save_imported_repository", fake_save)

    result = await skills.import_github_from_args(
        github_import_args(subfolder="skills/working")
    )

    assert result == 1
    assert calls == ["broken", "working"]
    assert saved_sources == ["acme/working"]


async def test_import_github_skips_truncated_tree_without_failing_successful_imports(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_calls: list[str] = []

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(
                import_repository("large-repository"),
                import_repository("working"),
            )

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            tree_calls.append(repo.repo)
            if repo.repo == "large-repository":
                raise skills.GitHubTreeTruncatedError(
                    "GitHub tree is truncated; repository scan skipped"
                )
            return [skills.GitHubTreeItem(path="skills/working/SKILL.md", type="blob")]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            return "---\nname: Working\n---\n"

    async def fake_save(
        imported: list[skills.ImportedSkill],
    ) -> list[tuple[SimpleNamespace, SimpleNamespace, str]]:
        item = imported[0]
        return [
            (
                SimpleNamespace(source=item.payload.source, slug=item.payload.slug),
                SimpleNamespace(content_hash="hash-working"),
                item.source_path,
            )
        ]

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "save_imported_repository", fake_save)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(
        github_import_args(subfolder="skills/working")
    )

    assert result == 0
    assert tree_calls == ["large-repository", "working"]
    assert capsys.readouterr().out.strip() == (
        "imported 1 skill(s) from 1 of 2 active GitHub repositories for acme: "
        "1 repositories skipped, 0 failed, 0 skills failed"
    )
    skipped_record = next(
        record
        for record in caplog.records
        if record.message == "github skills import repository skipped"
    )
    assert skipped_record.source == "acme/large-repository"
    assert skipped_record.skip_reason == (
        "GitHub tree is truncated; repository scan skipped"
    )


async def test_import_github_aborts_remaining_repositories_on_systemic_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls: list[str] = []

    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(
                import_repository("one"),
                import_repository("two"),
                import_repository("three"),
            )

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            resolve_calls.append(repo.repo)
            raise skills.GitHubSystemicError("GitHub server unavailable")

    def fail_if_database_opens() -> None:
        raise AssertionError("database should not open after a systemic GitHub failure")

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", fail_if_database_opens)

    result = await skills.import_github_from_args(github_import_args())

    assert result == 1
    assert resolve_calls == ["one"]
    assert capsys.readouterr().out.strip() == (
        "imported 0 skill(s) from 0 of 3 active GitHub repositories for acme: "
        "0 repositories skipped, 3 failed, 0 skills failed"
    )


async def test_import_github_reports_owner_discovery_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            raise skills.SkillCliError("GitHub user or organization not found: acme")

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)

    result = await skills.import_github_from_args(github_import_args())

    assert result == 1
    assert capsys.readouterr().out.strip() == (
        "imported 0 skill(s) from 0 of 0 active GitHub repositories for acme: "
        "0 repositories skipped, 0 failed, 0 skills failed; owner discovery failed"
    )


def test_import_github_rejects_duplicate_derived_slugs() -> None:
    imported = [
        SimpleNamespace(
            payload=SimpleNamespace(slug="duplicate"),
            source_path="skills/one/SKILL.md",
        ),
        SimpleNamespace(
            payload=SimpleNamespace(slug="duplicate"),
            source_path="skills/two/SKILL.md",
        ),
    ]

    with pytest.raises(skills.SkillCliError, match="multiple skill paths"):
        skills.validate_unique_imported_skill_slugs(imported)  # type: ignore[arg-type]


async def test_owner_import_matches_github_source_case_insensitively_and_preserves_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = SimpleNamespace(
        id="skill-id",
        source="Acme/Agent-Skills",
        slug="weather-skill",
        name="Old name",
        source_owner="Acme",
        source_name="Agent-Skills",
        source_owner_url="",
        source_owner_icon_url="",
        source_url="",
        description="Old description",
        install_url="",
        website_url="",
        repository={
            "type": "git",
            "source": "github",
            "url": "https://github.com/Acme/Agent-Skills",
            "subfolder": "skills/weather",
            "branch": "main",
        },
        status="quarantined",
        visibility="unlisted",
    )
    statements: list[str] = []

    class FakeSession:
        async def execute(self, statement: object) -> SimpleNamespace:
            statements.append(str(statement))
            if len(statements) == 1:
                return SimpleNamespace()
            return SimpleNamespace(scalar_one_or_none=lambda: skill)

    async def fake_upsert(
        session: object,
        selected_skill: object,
        *,
        skill_md: str,
        files: list[skills.SkillSnapshotFile],
    ) -> SimpleNamespace:
        assert selected_skill is skill
        return SimpleNamespace(content_hash="new-hash")

    async def fake_owner_upsert(session: object, payload: skills.SkillAddInput) -> None:
        return None

    payload = skills.SkillAddInput(
        source="acme/agent-skills",
        source_owner="acme",
        source_name="agent-skills",
        source_owner_url="https://github.com/acme",
        source_owner_icon_url="https://avatars.example/acme.png",
        source_url="https://github.com/acme/agent-skills",
        slug="weather",
        name="Weather",
        description="Weather APIs",
        skill_md="# Weather",
        files=[{"path": "SKILL.md", "contents": "# Weather"}],
        repository_url="https://github.com/acme/agent-skills",
        repository_subfolder="skills/weather",
        repository_ref="main",
    )
    monkeypatch.setattr(skills, "upsert_skill_snapshot", fake_upsert)
    monkeypatch.setattr(skills, "upsert_source_owner_metadata", fake_owner_upsert)

    result, _snapshot = await skills.add_skill(
        FakeSession(),  # type: ignore[arg-type]
        payload,
        preserve_catalog_state=True,
    )

    assert result is skill
    assert "pg_advisory_xact_lock" in statements[0]
    assert "lower(skills.source)" in statements[1]
    assert "skills.repository" in statements[1]
    assert skill.source == "Acme/Agent-Skills"
    assert skill.slug == "weather-skill"
    assert skill.status == "quarantined"
    assert skill.visibility == "unlisted"
    assert skill.name == "Weather"


async def test_import_github_ignores_nested_invalid_skill_and_commits_exact_subfolder(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            assert token == "github-token"
            assert timeout_seconds == 3.0

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(import_repository("agent-skills"))

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(
                default_branch="main",
                owner_avatar_url="https://avatars.example/acme.png",
            )

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            assert ref == RESOLVED_COMMIT_SHA
            return [
                skills.GitHubTreeItem(path="skills/SKILL.md", type="blob"),
                skills.GitHubTreeItem(path="skills/binary/SKILL.md", type="blob"),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            if path == "skills/binary/SKILL.md":
                raise skills.InvalidSkillTextError(
                    path,
                    "GitHub file contains a NUL byte at offset 42 (line 3)",
                )
            assert path == "skills/SKILL.md"
            return "---\nname: Weather Skill\ndescription: Weather APIs.\n---\n"

    commits = 0

    class FakeSessionContext:
        async def __aenter__(self) -> "FakeSessionContext":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            nonlocal commits
            commits += 1

    saved_paths: list[str] = []

    async def fake_add_skill(
        session: object,
        payload: skills.SkillAddInput,
        *,
        preserve_catalog_state: bool,
    ):
        assert preserve_catalog_state is True
        saved_paths.append(payload.repository_subfolder)
        return (
            SimpleNamespace(source=payload.source, slug=payload.slug),
            SimpleNamespace(content_hash="sha256:abc123"),
        )

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(skills, "add_skill", fake_add_skill)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(github_import_args())

    assert result == 0
    assert saved_paths == ["skills"]
    assert commits == 1
    output_lines = capsys.readouterr().out.splitlines()
    assert output_lines[-1] == (
        "imported 1 skill(s) from 1 of 1 active GitHub repositories for acme: "
        "0 repositories skipped, 0 failed, 0 skills failed"
    )

    records = [record for record in caplog.records if record.name == skills.logger.name]
    skipped_records = [
        record
        for record in records
        if record.message == "github skill import skipped invalid skill"
    ]
    assert skipped_records == []
    assert "github skills import failed" not in [record.message for record in records]

    completed_record = next(
        record for record in records if record.message == "github skills import completed"
    )
    assert completed_record.skill_count == 1
    assert completed_record.failed_skill_count == 0
    assert completed_record.matched_repository_count == 1


async def test_import_github_fails_when_all_discovered_skills_are_invalid(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(import_repository("agent-skills"))

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            return [
                skills.GitHubTreeItem(path="skills/binary/SKILL.md", type="blob"),
                skills.GitHubTreeItem(path="skills/not-utf8/SKILL.md", type="blob"),
            ]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            raise skills.InvalidSkillTextError(path, "Invalid SKILL.md")

    def fail_if_session_is_opened() -> None:
        raise AssertionError("database session should not open when no skill is importable")

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", fail_if_session_is_opened)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(
        github_import_args(subfolder="skills/binary")
    )

    assert result == 1
    records = [record for record in caplog.records if record.name == skills.logger.name]
    assert sum(
        record.message == "github skill import skipped invalid skill" for record in records
    ) == 1
    assert records[-1].message == "github skills import completed"
    assert records[-1].failed_skill_count == 1


@pytest.mark.parametrize(
    ("skill_paths", "failure_kind"),
        [
            (["skills/binary/SKILL.md"], "invalid-text"),
            (["skills/unavailable/SKILL.md"], "http"),
        ],
)
async def test_import_github_isolates_invalid_skill_and_repository_fetch_errors(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    skill_paths: list[str],
    failure_kind: str,
) -> None:
    class FakeGitHubClient:
        def __init__(self, *, token: str, timeout_seconds: float) -> None:
            pass

        async def __aenter__(self) -> "FakeGitHubClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def list_active_repositories(
            self,
            owner: str,
        ) -> skills.GitHubRepositoryListing:
            return repository_listing(import_repository("agent-skills"))

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            return skills.GitHubRepositoryMetadata(default_branch="main", owner_avatar_url="")

        async def resolve_commit_sha(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> str:
            return RESOLVED_COMMIT_SHA

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            return [skills.GitHubTreeItem(path=path, type="blob") for path in skill_paths]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            if failure_kind == "invalid-text":
                raise skills.InvalidSkillTextError(path, "Invalid SKILL.md")
            raise skills.SkillCliError(f"GitHub raw file fetch failed for {path}: unavailable")

    def fail_if_session_is_opened() -> None:
        raise AssertionError("database session should not open after a fatal fetch error")

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", fail_if_session_is_opened)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(
        github_import_args(subfolder=skill_paths[0].removesuffix("/SKILL.md"))
    )

    assert result == 1
    records = [record for record in caplog.records if record.name == skills.logger.name]
    invalid_logs = [
        record
        for record in records
        if record.message == "github skill import skipped invalid skill"
    ]
    assert len(invalid_logs) == (1 if failure_kind == "invalid-text" else 0)
    assert records[-1].message == "github skills import completed"
    assert records[-1].failed_skill_count == (1 if failure_kind == "invalid-text" else 0)
    assert records[-1].failed_repository_count == (1 if failure_kind == "http" else 0)


def test_manage_dispatches_skills_mark_official(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    async def fake_mark_official_from_args(args) -> int:
        called["owner"] = args.owner
        called["source_type"] = args.source_type
        called["unset"] = args.unset
        return 0

    monkeypatch.setattr(manage, "mark_official_from_args", fake_mark_official_from_args)

    result = manage.main(["skills", "mark-official", "vercel-labs"])

    assert result == 0
    assert called == {"owner": "vercel-labs", "source_type": "github", "unset": False}


def test_validate_skill_owner_rejects_source() -> None:
    with pytest.raises(skills.SkillCliError, match="owner"):
        skills.validate_skill_owner("vercel-labs/skills")
