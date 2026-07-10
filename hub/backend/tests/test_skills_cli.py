import logging
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import manage
from app.cli import skills


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


def test_discover_skill_paths_uses_exact_skill_subfolder() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/nested/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, subfolder="skills/weather") == [
        "skills/weather/SKILL.md"
    ]


def test_discover_skill_paths_recurses_under_parent_subfolder() -> None:
    tree = [
        skills.GitHubTreeItem(path="SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="skills/docs/SKILL.md", type="blob", size=50),
        skills.GitHubTreeItem(path="examples/demo/SKILL.md", type="blob", size=50),
    ]

    assert skills.discover_skill_paths(tree, subfolder="skills") == [
        "skills/docs/SKILL.md",
        "skills/weather/SKILL.md",
    ]


def test_skill_slug_root_is_relative_to_import_subfolder() -> None:
    assert skills.skill_slug_root("skills/algorithmic-art", "skills") == "algorithmic-art"


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
        called["repository_url"] = args.repository_url
        called["subfolder"] = args.subfolder
        return 0

    monkeypatch.setattr(manage, "import_github_from_args", fake_import_github_from_args)

    result = manage.main(
        [
            "skills",
            "import-github",
            "https://github.com/acme/agent-skills",
            "--subfolder",
            "skills/weather",
        ]
    )

    assert result == 0
    assert called == {
        "repository_url": "https://github.com/acme/agent-skills",
        "subfolder": "skills/weather",
    }


def test_manage_import_github_rejects_removed_curated_flag() -> None:
    with pytest.raises(SystemExit):
        manage.main(
            [
                "skills",
                "import-github",
                "https://github.com/acme/agent-skills",
                "--curated",
            ]
        )


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

        async def repository_metadata(
            self,
            repo: skills.GitHubRepository,
        ) -> skills.GitHubRepositoryMetadata:
            assert repo.source == "acme/agent-skills"
            return skills.GitHubRepositoryMetadata(
                default_branch="main",
                owner_avatar_url="https://avatars.example/acme.png",
            )

        async def recursive_tree(
            self,
            repo: skills.GitHubRepository,
            ref: str,
        ) -> list[skills.GitHubTreeItem]:
            assert repo.source == "acme/agent-skills"
            assert ref == "main"
            return [skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob")]

        async def raw_file(
            self,
            repo: skills.GitHubRepository,
            ref: str,
            path: str,
        ) -> str:
            assert repo.source == "acme/agent-skills"
            assert ref == "main"
            assert path == "skills/weather/SKILL.md"
            return "---\nname: Weather Skill\ndescription: Weather APIs.\n---\n"

    class FakeSessionContext:
        async def __aenter__(self) -> "FakeSessionContext":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    async def fake_add_skill(session: object, payload: skills.SkillAddInput):
        assert payload.source == "acme/agent-skills"
        assert payload.repository_subfolder == "skills/weather"
        return (
            SimpleNamespace(source=payload.source, slug=payload.slug),
            SimpleNamespace(content_hash="sha256:abc123"),
        )

    monkeypatch.setattr(skills, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(skills, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(skills, "add_skill", fake_add_skill)
    caplog.set_level(logging.INFO, logger=skills.logger.name)

    result = await skills.import_github_from_args(
        Namespace(
            repository_url="https://github.com/acme/agent-skills",
            subfolder="skills",
            ref="",
            slug="",
            name="",
            description="",
            install_url="",
            website_url="",
            github_token="github-token",
            timeout_seconds=3.0,
        )
    )

    assert result == 0
    records = [record for record in caplog.records if record.name == skills.logger.name]
    assert [record.message for record in records] == [
        "github skills import started",
        "github skills import repository resolved",
        "github skills import tree fetched",
        "github skills import discovered skills",
        "github skill import fetched skill file",
        "github skill import saved skill",
        "github skills import completed",
    ]
    start_record = records[0]
    assert start_record.repository_url == "https://github.com/acme/agent-skills"
    assert start_record.github_token_configured is True
    assert not hasattr(start_record, "github_token")
    discovered_record = records[3]
    assert discovered_record.skill_count == 1
    assert discovered_record.skill_paths == ["skills/weather/SKILL.md"]
    saved_record = records[5]
    assert saved_record.skill_id == "acme/agent-skills/weather-skill"
    assert saved_record.source_path == "skills/weather/SKILL.md"
    assert records[6].skill_count == 1


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
