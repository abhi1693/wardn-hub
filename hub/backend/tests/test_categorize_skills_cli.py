import json
import uuid
from types import SimpleNamespace

import pytest

from app.cli import categorize_skills as cli
from app.modules.skills import repository


def category(slug: str = "developer-tools") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug=slug,
        name="Developer Tools",
        description="Developer productivity.",
    )


def target() -> repository.SkillCategorizationTarget:
    return repository.SkillCategorizationTarget(
        skill_id=uuid.uuid4(),
        source="acme/skills",
        slug="code-review",
        name="Code Review",
        description="Review code changes.",
        skill_md="# Code Review\n\nUse this skill for source code review.",
    )


def test_category_decision_schema_restricts_slugs_to_existing_categories() -> None:
    schema = cli.category_decision_output_schema([category("developer-tools")])

    assert schema["properties"]["categorySlug"]["anyOf"][0]["enum"] == ["developer-tools"]


async def test_categorize_skill_targets_writes_llm_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[str, str]] = []
    current_target = target()

    class FakeReviewer:
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            assert "categoryCatalog" in prompt
            assert "developer-tools" in prompt
            assert environment == {"WARDN_HUB_SKILL_ID": current_target.catalog_id}
            return json.dumps(
                {
                    "decision": "assign",
                    "categorySlug": "developer-tools",
                    "confidence": "high",
                    "rationale": "The skill is primarily for code review.",
                }
            )

    async def fake_write(
        write_target: repository.SkillCategorizationTarget,
        category_slug: str,
    ) -> None:
        writes.append((write_target.catalog_id, category_slug))

    monkeypatch.setattr(cli, "write_category_assignment", fake_write)

    stats = await cli.categorize_skill_targets(
        reviewer=FakeReviewer(),
        targets=[current_target],
        categories=[category("developer-tools")],  # type: ignore[list-item]
    )

    assert stats.categorized == 1
    assert stats.failed == 0
    assert writes == [(current_target.catalog_id, "developer-tools")]


async def test_categorize_skill_targets_leaves_skipped_skill_uncategorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[str, str]] = []

    class FakeReviewer:
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            return json.dumps(
                {
                    "decision": "skip",
                    "categorySlug": None,
                    "confidence": "low",
                    "rationale": "The skill text is too generic.",
                }
            )

    async def fake_write(
        write_target: repository.SkillCategorizationTarget,
        category_slug: str,
    ) -> None:
        writes.append((write_target.catalog_id, category_slug))

    monkeypatch.setattr(cli, "write_category_assignment", fake_write)

    stats = await cli.categorize_skill_targets(
        reviewer=FakeReviewer(),
        targets=[target()],
        categories=[category("developer-tools")],  # type: ignore[list-item]
    )

    assert stats.skipped == 1
    assert stats.categorized == 0
    assert writes == []


async def test_categorize_skills_requires_codex_app_server_url() -> None:
    with pytest.raises(cli.UserFacingError, match=cli.CODEX_APP_SERVER_URL_ENV):
        await cli.categorize_skills_from_options(codex_app_server_url="")
