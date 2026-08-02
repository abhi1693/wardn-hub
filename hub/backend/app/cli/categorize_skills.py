from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.cli.codex_app_server import CodexAppServerReviewer, UserFacingError
from app.core.codex import CODEX_APP_SERVER_AUTH_TOKEN_ENV, CODEX_APP_SERVER_URL_ENV
from app.db.session import AsyncSessionLocal
from app.modules.registry.models import RegistryCategory
from app.modules.skills import repository

DEFAULT_CATEGORIZATION_LIMIT = 50
DEFAULT_CATEGORIZATION_TIMEOUT_SECONDS = 600
MAX_SKILL_MD_PROMPT_CHARS = 30_000


class SkillCategoryDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["assign", "skip"]
    category_slug: str | None = Field(default=None, alias="categorySlug")
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_assignment(self) -> SkillCategoryDecisionPayload:
        if self.decision == "assign" and not self.category_slug:
            raise ValueError("categorySlug is required when decision is assign")
        if self.decision == "skip" and self.category_slug is not None:
            raise ValueError("categorySlug must be null when decision is skip")
        return self


class Reviewer(Protocol):
    async def review_async(self, prompt: str, *, environment: dict[str, str]) -> str:
        """Return a schema-constrained category decision from async code."""


@dataclass
class CategorizationStats:
    seen: int = 0
    categorized: int = 0
    skipped: int = 0
    failed: int = 0


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n\n[truncated after {limit} characters]"


def category_decision_output_schema(categories: list[RegistryCategory]) -> dict[str, Any]:
    slugs = [category.slug for category in categories]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision", "categorySlug", "confidence", "rationale"],
        "properties": {
            "decision": {"type": "string", "enum": ["assign", "skip"]},
            "categorySlug": {
                "anyOf": [
                    {"type": "string", "enum": slugs},
                    {"type": "null"},
                ]
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 1000},
        },
    }


def categorization_prompt(
    target: repository.SkillCategorizationTarget,
    categories: list[RegistryCategory],
) -> str:
    category_catalog = [
        {
            "slug": category.slug,
            "name": category.name,
            "description": category.description,
        }
        for category in categories
    ]
    skill_payload = {
        "id": target.catalog_id,
        "source": target.source,
        "slug": target.slug,
        "name": target.name,
        "description": target.description,
        "skillMd": truncate_text(target.skill_md, MAX_SKILL_MD_PROMPT_CHARS),
    }
    return f"""Categorize one Wardn Hub agent skill using only the existing category catalog.

Rules:
- Choose exactly one category slug when the skill has a clear primary use case.
- Return skip with categorySlug null when the supplied text is too generic or
  does not support an existing category.
- Use only category slugs from categoryCatalog. Do not invent, rename, or broaden categories.
- Prefer the skill's user-facing capability over implementation details or incidental technologies.
- Return only the JSON object required by the schema.

categoryCatalog:
{json.dumps(category_catalog, ensure_ascii=False, indent=2, sort_keys=True)}

skill:
{json.dumps(skill_payload, ensure_ascii=False, indent=2, sort_keys=True)}
"""


def parse_category_decision(
    raw_response: str,
    *,
    valid_slugs: set[str],
) -> SkillCategoryDecisionPayload:
    try:
        decision = SkillCategoryDecisionPayload.model_validate_json(raw_response)
    except ValidationError as exc:
        raise UserFacingError(
            "LLM did not return a valid schema-constrained categorization response"
        ) from exc
    if decision.category_slug is not None and decision.category_slug not in valid_slugs:
        raise UserFacingError(f"LLM selected an unknown category slug: {decision.category_slug}")
    return decision


async def load_categorization_inputs(
    *,
    limit: int,
    skill_id: str | None,
    include_categorized: bool,
) -> tuple[list[RegistryCategory], list[repository.SkillCategorizationTarget]]:
    async with AsyncSessionLocal() as session:
        categories = await repository.list_active_categories(session)
        if not categories:
            raise UserFacingError("no active categories are available")
        targets = await repository.list_skill_categorization_targets(
            session,
            limit=limit,
            skill_id=skill_id,
            include_categorized=include_categorized,
        )
    return categories, targets


async def write_category_assignment(
    target: repository.SkillCategorizationTarget,
    category_slug: str,
) -> None:
    async with AsyncSessionLocal() as session:
        await repository.replace_skill_categories(
            session,
            skill_id=target.skill_id,
            category_slugs=[category_slug],
            source="llm",
        )
        await session.commit()


async def categorize_skill_targets(
    *,
    reviewer: Reviewer,
    targets: list[repository.SkillCategorizationTarget],
    categories: list[RegistryCategory],
    dry_run: bool = False,
    stdout: TextIO = sys.stdout,
) -> CategorizationStats:
    stats = CategorizationStats()
    valid_slugs = {category.slug for category in categories}

    for target in targets:
        stats.seen += 1
        try:
            raw_response = await reviewer.review_async(
                categorization_prompt(target, categories),
                environment={"WARDN_HUB_SKILL_ID": target.catalog_id},
            )
            decision = parse_category_decision(raw_response, valid_slugs=valid_slugs)
            if decision.decision == "skip" or decision.category_slug is None:
                stats.skipped += 1
                print(f"skipped {target.catalog_id}: {decision.rationale}", file=stdout)
                continue
            if not dry_run:
                await write_category_assignment(target, decision.category_slug)
            stats.categorized += 1
            action = "would categorize" if dry_run else "categorized"
            print(f"{action} {target.catalog_id}: {decision.category_slug}", file=stdout)
        except (UserFacingError, ValueError) as exc:
            stats.failed += 1
            print(f"failed {target.catalog_id}: {exc}", file=stdout)
    return stats


async def categorize_skills_from_options(
    *,
    codex_app_server_url: str,
    dry_run: bool = False,
    include_categorized: bool = False,
    max_skills: int = DEFAULT_CATEGORIZATION_LIMIT,
    skill_id: str | None = None,
    timeout_seconds: int = DEFAULT_CATEGORIZATION_TIMEOUT_SECONDS,
    stdout: TextIO = sys.stdout,
    reviewer: Reviewer | None = None,
) -> int:
    app_server_url = codex_app_server_url.strip()
    if not app_server_url:
        raise UserFacingError(
            f"Codex app-server categorization is required. Set {CODEX_APP_SERVER_URL_ENV} "
            "or pass --codex-app-server-url."
        )
    if max_skills <= 0:
        raise UserFacingError("max_skills must be positive")
    if timeout_seconds <= 0:
        raise UserFacingError("timeout_seconds must be positive")

    categories, targets = await load_categorization_inputs(
        limit=max_skills,
        skill_id=skill_id,
        include_categorized=include_categorized,
    )
    if not targets:
        print("no skill categories pending", file=stdout)
        return 0

    current_reviewer = reviewer or CodexAppServerReviewer(
        url=app_server_url,
        timeout_seconds=timeout_seconds,
        auth_token=os.getenv(CODEX_APP_SERVER_AUTH_TOKEN_ENV, "").strip(),
        analysis_only=True,
        structured_output_schema=category_decision_output_schema(categories),
    )
    stats = await categorize_skill_targets(
        reviewer=current_reviewer,
        targets=targets,
        categories=categories,
        dry_run=dry_run,
        stdout=stdout,
    )
    print(
        "skill categorization completed: "
        f"seen={stats.seen} categorized={stats.categorized} "
        f"skipped={stats.skipped} failed={stats.failed}",
        file=stdout,
    )
    return 1 if stats.failed else 0


async def categorize_skill_id_async(
    skill_id: str,
    *,
    codex_app_server_url: str | None = None,
    timeout_seconds: int = DEFAULT_CATEGORIZATION_TIMEOUT_SECONDS,
    stdout: TextIO = sys.stdout,
    reviewer: Reviewer | None = None,
) -> int:
    app_server_url = (codex_app_server_url or os.getenv(CODEX_APP_SERVER_URL_ENV, "")).strip()
    if not app_server_url and reviewer is None:
        print(
            f"skipped {skill_id}: {CODEX_APP_SERVER_URL_ENV} is not configured",
            file=stdout,
        )
        return 0
    if timeout_seconds <= 0:
        raise UserFacingError("timeout_seconds must be positive")

    categories, targets = await load_categorization_inputs(
        limit=1,
        skill_id=skill_id,
        include_categorized=True,
    )
    if not targets:
        print(f"no categorization target found for {skill_id}", file=stdout)
        return 0

    current_reviewer = reviewer or CodexAppServerReviewer(
        url=app_server_url,
        timeout_seconds=timeout_seconds,
        auth_token=os.getenv(CODEX_APP_SERVER_AUTH_TOKEN_ENV, "").strip(),
        analysis_only=True,
        structured_output_schema=category_decision_output_schema(categories),
    )
    stats = await categorize_skill_targets(
        reviewer=current_reviewer,
        targets=targets,
        categories=categories,
        dry_run=False,
        stdout=stdout,
    )
    return 1 if stats.failed else 0
