import logging
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import manage
from app.cli import skills

RESOLVED_COMMIT_SHA = "a" * 40


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
    async def fake_get(url: str) -> SimpleNamespace:
        assert url.endswith("/acme/agent-skills/main/skills/binary/SKILL.md")
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
    async def fake_get(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=500,
            content=b"",
            text="upstream failure",
        )

    repo = skills.parse_github_repository_url("https://github.com/acme/agent-skills")
    async with skills.GitHubClient() as client:
        monkeypatch.setattr(client._client, "get", fake_get)
        with pytest.raises(skills.SkillCliError) as exc_info:
            await client.raw_file(repo, "main", "skills/weather/SKILL.md")

    assert not isinstance(exc_info.value, skills.InvalidSkillTextError)
    assert str(exc_info.value) == (
        "GitHub raw file fetch failed for skills/weather/SKILL.md: upstream failure"
    )


async def test_github_raw_file_encodes_ref_and_path_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str) -> SimpleNamespace:
        assert url.endswith(
            "/feature/api%23v2/skills/weather/references/a%23b%3F%25%20file.txt"
        )
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
    with pytest.raises(skills.SkillCliError, match="pass --subfolder"):
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

    async def fake_add_skill(session: object, payload: skills.SkillAddInput):
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
    assert records[4].skill_file_count == 2
    saved_record = records[5]
    assert saved_record.skill_id == "acme/agent-skills/weather-skill"
    assert saved_record.source_path == "skills/weather/SKILL.md"
    assert records[6].skill_count == 1
    assert records[6].skipped_skill_count == 0
    assert records[6].discovered_skill_count == 1


async def test_import_github_skips_invalid_skill_and_commits_valid_skills(
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
                skills.GitHubTreeItem(path="skills/binary/SKILL.md", type="blob"),
                skills.GitHubTreeItem(path="skills/weather/SKILL.md", type="blob"),
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
            assert path == "skills/weather/SKILL.md"
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

    async def fake_add_skill(session: object, payload: skills.SkillAddInput):
        saved_paths.append(payload.repository_subfolder)
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
    assert saved_paths == ["skills/weather"]
    assert commits == 1
    output_lines = capsys.readouterr().out.splitlines()
    assert output_lines[-2:] == [
        "imported 1 skill(s)",
        "skipped 1 invalid skill(s)",
    ]

    records = [record for record in caplog.records if record.name == skills.logger.name]
    skipped_records = [
        record
        for record in records
        if record.message == "github skill import skipped invalid skill"
    ]
    assert len(skipped_records) == 1
    assert skipped_records[0].levelno == logging.WARNING
    assert skipped_records[0].source_path == "skills/binary/SKILL.md"
    assert skipped_records[0].skip_reason == (
        "GitHub file contains a NUL byte at offset 42 (line 3): skills/binary/SKILL.md"
    )
    assert "github skills import failed" not in [record.message for record in records]

    completed_record = next(
        record for record in records if record.message == "github skills import completed"
    )
    assert completed_record.skill_count == 1
    assert completed_record.skipped_skill_count == 1
    assert completed_record.discovered_skill_count == 2


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

    with pytest.raises(skills.SkillCliError):
        await skills.import_github_from_args(
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

    records = [record for record in caplog.records if record.name == skills.logger.name]
    assert sum(
        record.message == "github skill import skipped invalid skill" for record in records
    ) == 2
    assert "github skills import completed" not in [record.message for record in records]
    assert records[-1].message == "github skills import failed"


@pytest.mark.parametrize(
    ("skill_paths", "failure_kind"),
    [
        (["skills/binary/SKILL.md"], "invalid-text"),
        (
            ["skills/unavailable/SKILL.md", "skills/weather/SKILL.md"],
            "http",
        ),
    ],
)
async def test_import_github_does_not_skip_targeted_or_non_text_errors(
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

    with pytest.raises(skills.SkillCliError):
        await skills.import_github_from_args(
            Namespace(
                repository_url="https://github.com/acme/agent-skills",
                subfolder="skills" if len(skill_paths) > 1 else "skills/binary",
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

    records = [record for record in caplog.records if record.name == skills.logger.name]
    assert "github skill import skipped invalid skill" not in [
        record.message for record in records
    ]
    assert "github skills import completed" not in [record.message for record in records]
    assert records[-1].message == "github skills import failed"


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
