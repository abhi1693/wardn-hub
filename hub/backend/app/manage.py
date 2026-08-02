from __future__ import annotations

import asyncio
import os
from argparse import ArgumentTypeError, Namespace
from enum import StrEnum
from typing import Annotated, Any

import typer
from typer import _click as click

from app.cli.audit_skills import (
    CODEX_APP_SERVER_URL_ENV,
    DEFAULT_SCANNER_TIMEOUT_SECONDS,
    UserFacingError,
    audit_skills_from_args,
    skill_id_argument,
)
from app.cli.categorize_skills import (
    DEFAULT_CATEGORIZATION_LIMIT,
    DEFAULT_CATEGORIZATION_TIMEOUT_SECONDS,
    categorize_skills_from_options,
)
from app.cli.categorize_skills import (
    UserFacingError as CategorizationUserFacingError,
)
from app.cli.skills import (
    DEFAULT_IMPORT_TIMEOUT_SECONDS,
    GITHUB_IMPORT_OUTPUT_FORMATS,
    GITHUB_TOKEN_ENV,
    SkillCliError,
    add_skill_from_args,
    github_language_argument,
    github_owner_argument,
    github_repository_argument,
    github_repository_name_argument,
    github_timestamp_argument,
    github_topic_argument,
    import_github_from_args,
    import_subfolder_argument,
    mark_official_from_args,
    nonnegative_int_argument,
    positive_int_argument,
    run_import_github_command,
    run_refresh_github_command,
    validate_skill_source,
)
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.modules.registry.service import seed_default_categories


class SourceType(StrEnum):
    github = "github"
    well_known = "well-known"


class GitHubImportOutput(StrEnum):
    json = "json"
    text = "text"


app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    help="Manage Wardn Hub backend data and maintenance jobs.",
)
skills_app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Manage skills.",
)
app.add_typer(skills_app, name="skills")


async def seed_categories() -> int:
    async with AsyncSessionLocal() as session:
        response = await seed_default_categories(session)
        await session.commit()
    print(f"seeded {len(response.categories)} MCP categories")
    return 0


def _argument_error(exc: ArgumentTypeError | SkillCliError) -> click.exceptions.BadParameter:
    return click.exceptions.BadParameter(str(exc))


def _parse_argument(parser: Any, value: str) -> Any:
    try:
        return parser(value)
    except (ArgumentTypeError, SkillCliError) as exc:
        raise _argument_error(exc) from exc


def _parse_optional_argument(parser: Any, value: str | None) -> Any:
    if value is None:
        return None
    return _parse_argument(parser, value)


def _parse_repeated_argument(parser: Any, values: list[str] | None) -> list[Any]:
    return [_parse_argument(parser, value) for value in values or []]


def _source_type_value(source_type: SourceType) -> str:
    return source_type.value


@app.callback()
def app_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the management CLI version.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    if version:
        typer.echo("wardn-hub manage 0.1.0")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command("seed-categories", help="Seed the default MCP category taxonomy.")
def seed_categories_command() -> int:
    return asyncio.run(seed_categories())


@skills_app.command("add", help="Add or update a skill from SKILL.md.")
def skills_add(
    source: Annotated[str, typer.Option("--source", help="GitHub source in owner/repo form.")],
    skill_file: Annotated[
        str,
        typer.Option(
            "--skill-file",
            help="Path to the local SKILL.md file. Defaults to ./SKILL.md.",
        ),
    ] = "SKILL.md",
    slug: Annotated[str, typer.Option("--slug", help="Skill slug. Defaults from name.")] = "",
    name: Annotated[str, typer.Option("--name", help="Skill display name.")] = "",
    description: Annotated[str, typer.Option("--description", help="Skill description.")] = "",
    source_type: Annotated[
        SourceType,
        typer.Option("--source-type", help="Skill source type."),
    ] = SourceType.github,
    source_owner: Annotated[
        str,
        typer.Option("--source-owner", help="Source owner, org, or publisher."),
    ] = "",
    source_name: Annotated[
        str,
        typer.Option("--source-name", help="Source repository or package name."),
    ] = "",
    source_owner_url: Annotated[
        str,
        typer.Option("--source-owner-url", help="Source owner URL."),
    ] = "",
    source_owner_icon_url: Annotated[
        str,
        typer.Option("--source-owner-icon-url", help="Source owner icon URL."),
    ] = "",
    source_url: Annotated[str, typer.Option("--source-url", help="Source URL.")] = "",
    install_url: Annotated[str, typer.Option("--install-url", help="Install/source URL.")] = "",
    website_url: Annotated[str, typer.Option("--website-url", help="Website or docs URL.")] = "",
    repository_url: Annotated[str, typer.Option("--repository-url", help="Repository URL.")] = "",
) -> int:
    source_type_value = _source_type_value(source_type)
    try:
        validated_source = validate_skill_source(source, source_type=source_type_value)
    except SkillCliError as exc:
        raise _argument_error(exc) from exc
    return asyncio.run(
        add_skill_from_args(
            Namespace(
                source=validated_source,
                skill_file=skill_file,
                slug=slug,
                name=name,
                description=description,
                source_type=source_type_value,
                source_owner=source_owner,
                source_name=source_name,
                source_owner_url=source_owner_url,
                source_owner_icon_url=source_owner_icon_url,
                source_url=source_url,
                install_url=install_url,
                website_url=website_url,
                repository_url=repository_url,
            )
        )
    )


@skills_app.command(
    "import-github",
    help="Search and stream matching GitHub repositories into the skills catalog.",
)
def skills_import_github(
    owner: Annotated[
        str | None,
        typer.Argument(help="Optional legacy GitHub user or organization login."),
    ] = None,
    owners: Annotated[
        list[str] | None,
        typer.Option(
            "--owner",
            help="Auto-detected GitHub user or organization. Repeat to target several owners.",
        ),
    ] = None,
    organizations: Annotated[
        list[str] | None,
        typer.Option(
            "--org",
            help="GitHub organization to search. Repeat to target several organizations.",
        ),
    ] = None,
    users: Annotated[
        list[str] | None,
        typer.Option("--user", help="GitHub user to search. Repeat to target several users."),
    ] = None,
    repositories: Annotated[
        list[str] | None,
        typer.Option(
            "--repo",
            help="GitHub repository in owner/repo form. Repeat to target several repositories.",
        ),
    ] = None,
    all_github: Annotated[
        bool,
        typer.Option("--all-github", help="Search all public GitHub repositories."),
    ] = False,
    output: Annotated[
        GitHubImportOutput,
        typer.Option(
            "--output",
            help="Importer log output format. Use text for tab-separated logs.",
        ),
    ] = GitHubImportOutput.json,
    subfolder: Annotated[
        str | None,
        typer.Option(
            "--subfolder",
            help=(
                "Repository subfolder containing SKILL.md. When omitted, the repository "
                "root is the selected scope."
            ),
        ),
    ] = None,
    recursive: Annotated[
        bool,
        typer.Option("--recursive", help="Import every SKILL.md under the selected scope."),
    ] = False,
    min_stars: Annotated[
        str | None,
        typer.Option("--min-stars", help="Only repositories with at least this many stars."),
    ] = None,
    max_stars: Annotated[
        str | None,
        typer.Option("--max-stars", help="Only repositories with at most this many stars."),
    ] = None,
    active_within_days: Annotated[
        str | None,
        typer.Option(
            "--active-within-days",
            help="Only repositories pushed to within this many days.",
        ),
    ] = None,
    pushed_after: Annotated[
        str | None,
        typer.Option(
            "--pushed-after",
            help="Only repositories pushed on or after this ISO-8601 date or datetime.",
        ),
    ] = None,
    pushed_before: Annotated[
        str | None,
        typer.Option(
            "--pushed-before",
            help="Only repositories pushed on or before this ISO-8601 date or datetime.",
        ),
    ] = None,
    created_after: Annotated[
        str | None,
        typer.Option(
            "--created-after",
            help="Only repositories created on or after this ISO-8601 date or datetime.",
        ),
    ] = None,
    created_before: Annotated[
        str | None,
        typer.Option(
            "--created-before",
            help="Only repositories created on or before this ISO-8601 date or datetime.",
        ),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Only repositories whose primary language matches."),
    ] = None,
    repository_names: Annotated[
        list[str] | None,
        typer.Option(
            "--repo-name",
            help="Only repositories whose name matches this term. Repeat as needed.",
        ),
    ] = None,
    excluded_organizations: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-org",
            help="Exclude repositories owned by this GitHub organization. Repeat as needed.",
        ),
    ] = None,
    excluded_users: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-user",
            help="Exclude repositories owned by this GitHub user. Repeat as needed.",
        ),
    ] = None,
    exclude_existing_owners: Annotated[
        bool,
        typer.Option(
            "--exclude-existing-owners",
            help="Exclude GitHub owners already represented in Hub.",
        ),
    ] = False,
    excluded_repositories: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-repo",
            help="Exclude this GitHub repository in owner/repo form. Repeat as needed.",
        ),
    ] = None,
    excluded_repository_names: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-repo-name",
            help="Exclude repositories whose name contains this term. Repeat as needed.",
        ),
    ] = None,
    topics: Annotated[
        list[str] | None,
        typer.Option("--topic", help="Required GitHub repository topic. Repeat as needed."),
    ] = None,
    verified_orgs_only: Annotated[
        bool,
        typer.Option(
            "--verified-orgs-only",
            help="Only import repositories owned by GitHub-verified organizations.",
        ),
    ] = False,
    max_repositories: Annotated[
        str | None,
        typer.Option(
            "--max-repositories",
            help="Stop after this many matching active repositories.",
        ),
    ] = None,
    github_token: Annotated[
        str,
        typer.Option(
            "--github-token",
            help=f"GitHub token. Defaults to ${GITHUB_TOKEN_ENV} when set.",
        ),
    ] = "",
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", help="GitHub request timeout in seconds."),
    ] = DEFAULT_IMPORT_TIMEOUT_SECONDS,
    ) -> int:
    if output.value not in GITHUB_IMPORT_OUTPUT_FORMATS:
        raise click.exceptions.BadParameter("output must be one of: json, text")
    args = Namespace(
        owner=_parse_optional_argument(github_owner_argument, owner),
        owners=_parse_repeated_argument(github_owner_argument, owners),
        organizations=_parse_repeated_argument(github_owner_argument, organizations),
        users=_parse_repeated_argument(github_owner_argument, users),
        repositories=_parse_repeated_argument(github_repository_argument, repositories),
        all_github=all_github,
        output=output.value,
        subfolder=_parse_optional_argument(import_subfolder_argument, subfolder),
        recursive=recursive,
        min_stars=_parse_optional_argument(nonnegative_int_argument, min_stars),
        max_stars=_parse_optional_argument(nonnegative_int_argument, max_stars),
        active_within_days=_parse_optional_argument(positive_int_argument, active_within_days),
        pushed_after=_parse_optional_argument(github_timestamp_argument, pushed_after),
        pushed_before=_parse_optional_argument(github_timestamp_argument, pushed_before),
        created_after=_parse_optional_argument(github_timestamp_argument, created_after),
        created_before=_parse_optional_argument(github_timestamp_argument, created_before),
        language=_parse_optional_argument(github_language_argument, language),
        repository_names=_parse_repeated_argument(
            github_repository_name_argument,
            repository_names,
        ),
        excluded_organizations=_parse_repeated_argument(
            github_owner_argument,
            excluded_organizations,
        ),
        excluded_users=_parse_repeated_argument(github_owner_argument, excluded_users),
        exclude_existing_owners=exclude_existing_owners,
        excluded_repositories=_parse_repeated_argument(
            github_repository_argument,
            excluded_repositories,
        ),
        excluded_repository_names=_parse_repeated_argument(
            github_repository_name_argument,
            excluded_repository_names,
        ),
        topics=_parse_repeated_argument(github_topic_argument, topics),
        verified_orgs_only=verified_orgs_only,
        max_repositories=_parse_optional_argument(positive_int_argument, max_repositories),
        github_token=github_token,
        timeout_seconds=timeout_seconds,
    )
    try:
        configure_logging()
        return run_import_github_command(args, importer=import_github_from_args)
    except SkillCliError as exc:
        raise click.exceptions.UsageError(str(exc)) from exc


@skills_app.command(
    "refresh",
    help="Refresh snapshot bundles for all active GitHub skills.",
)
def skills_refresh(
    github_token: Annotated[
        str,
        typer.Option(
            "--github-token",
            help=f"GitHub token override. Defaults to ${GITHUB_TOKEN_ENV} when set.",
        ),
    ] = "",
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", help="GitHub request timeout in seconds."),
    ] = DEFAULT_IMPORT_TIMEOUT_SECONDS,
) -> int:
    configure_logging()
    return run_refresh_github_command(
        Namespace(
            github_token=github_token,
            timeout_seconds=timeout_seconds,
        )
    )


@skills_app.command("audit", help="Audit every unaudited current public skill snapshot.")
def skills_audit(
    skill_id: Annotated[
        str | None,
        typer.Option(
            "--skill-id",
            help="Audit exactly one catalog skill ID in owner/repository/slug form.",
        ),
    ] = None,
    max_skills: Annotated[
        str | None,
        typer.Option("--max-skills", help="Stop after visiting this many snapshots."),
    ] = None,
    reaudit: Annotated[
        bool,
        typer.Option(
            "--reaudit",
            help="Rescan matching snapshots even when their audit is current.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Run the complete Cisco scan without database writes."),
    ] = False,
    scanner_timeout: Annotated[
        str,
        typer.Option("--scanner-timeout", help="Seconds to wait for each Cisco scan."),
    ] = str(DEFAULT_SCANNER_TIMEOUT_SECONDS),
    codex_app_server_url: Annotated[
        str,
        typer.Option(
            "--codex-app-server-url",
            help="Codex app-server WebSocket URL used by the optional LLM analyzer.",
        ),
    ] = os.getenv(CODEX_APP_SERVER_URL_ENV, ""),
) -> int:
    try:
        configure_logging()
        return audit_skills_from_args(
            Namespace(
                skill_id=_parse_optional_argument(skill_id_argument, skill_id),
                max_skills=_parse_optional_argument(positive_int_argument, max_skills),
                reaudit=reaudit,
                dry_run=dry_run,
                scanner_timeout=_parse_argument(positive_int_argument, scanner_timeout),
                codex_app_server_url=codex_app_server_url,
            )
        )
    except UserFacingError as exc:
        raise click.exceptions.UsageError(str(exc)) from exc


@skills_app.command("categorize", help="Ask Codex app-server to assign existing categories.")
def skills_categorize(
    skill_id: Annotated[
        str | None,
        typer.Option(
            "--skill-id",
            help="Categorize exactly one catalog skill ID in owner/repository/slug form.",
        ),
    ] = None,
    max_skills: Annotated[
        str,
        typer.Option("--max-skills", help="Stop after categorizing this many skills."),
    ] = str(DEFAULT_CATEGORIZATION_LIMIT),
    include_categorized: Annotated[
        bool,
        typer.Option(
            "--include-categorized",
            help="Reconsider skills that already have a category assignment.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Ask the LLM but do not write category assignments."),
    ] = False,
    timeout_seconds: Annotated[
        str,
        typer.Option("--timeout-seconds", help="Seconds to wait for each Codex response."),
    ] = str(DEFAULT_CATEGORIZATION_TIMEOUT_SECONDS),
    codex_app_server_url: Annotated[
        str,
        typer.Option(
            "--codex-app-server-url",
            help=(
                "Codex app-server WebSocket URL used for skill categorization. "
                f"Defaults to ${CODEX_APP_SERVER_URL_ENV}."
            ),
        ),
    ] = os.getenv(CODEX_APP_SERVER_URL_ENV, ""),
) -> int:
    try:
        return asyncio.run(
            categorize_skills_from_options(
                codex_app_server_url=codex_app_server_url,
                dry_run=dry_run,
                include_categorized=include_categorized,
                max_skills=_parse_argument(positive_int_argument, max_skills),
                skill_id=_parse_optional_argument(skill_id_argument, skill_id),
                timeout_seconds=_parse_argument(positive_int_argument, timeout_seconds),
            )
        )
    except CategorizationUserFacingError as exc:
        raise click.exceptions.UsageError(str(exc)) from exc


@skills_app.command("mark-official", help="Mark a source owner as official.")
def skills_mark_official(
    owner: Annotated[str, typer.Argument(help="Skill owner, for example vercel-labs.")],
    source_type: Annotated[
        SourceType,
        typer.Option("--source-type", help="Skill source type."),
    ] = SourceType.github,
    owner_url: Annotated[str, typer.Option("--owner-url", help="Official owner URL.")] = "",
    owner_icon_url: Annotated[
        str,
        typer.Option("--owner-icon-url", help="Official owner icon URL."),
    ] = "",
    unset: Annotated[
        bool,
        typer.Option("--unset", help="Remove official status from the source owner."),
    ] = False,
) -> int:
    return asyncio.run(
        mark_official_from_args(
            Namespace(
                owner=owner,
                source_type=_source_type_value(source_type),
                owner_url=owner_url,
                owner_icon_url=owner_icon_url,
                unset=unset,
            )
        )
    )


def main(argv: list[str] | None = None) -> int:
    try:
        result = app(
            args=argv,
            prog_name="python -m app.manage",
            standalone_mode=False,
        )
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.exceptions.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code) from exc
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
