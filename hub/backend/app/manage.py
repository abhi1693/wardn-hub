import argparse
import asyncio

from app.cli.audit_skills import UserFacingError, add_audit_arguments, audit_skills_from_args
from app.cli.skills import (
    DEFAULT_IMPORT_TIMEOUT_SECONDS,
    GITHUB_TOKEN_ENV,
    SkillCliError,
    add_import_github_arguments,
    add_skill_from_args,
    import_github_from_args,
    mark_official_from_args,
    run_import_github_command,
    run_refresh_github_command,
)
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.modules.registry.service import seed_default_categories


async def seed_categories() -> int:
    async with AsyncSessionLocal() as session:
        response = await seed_default_categories(session)
        await session.commit()
    print(f"seeded {len(response.categories)} MCP categories")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("seed-categories", help="Seed the default MCP category taxonomy.")
    skills_parser = subparsers.add_parser("skills", help="Manage skills.")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    skills_add = skills_subparsers.add_parser("add", help="Add or update a skill from SKILL.md.")
    skills_add.add_argument("--source", required=True, help="GitHub source in owner/repo form.")
    skills_add.add_argument(
        "--skill-file",
        default="SKILL.md",
        help="Path to the local SKILL.md file. Defaults to ./SKILL.md.",
    )
    skills_add.add_argument("--slug", default="", help="Skill slug. Defaults from name.")
    skills_add.add_argument("--name", default="", help="Skill display name.")
    skills_add.add_argument("--description", default="", help="Skill description.")
    skills_add.add_argument(
        "--source-type",
        default="github",
        choices=["github", "well-known"],
        help="Skill source type.",
    )
    skills_add.add_argument("--source-owner", default="", help="Source owner, org, or publisher.")
    skills_add.add_argument("--source-name", default="", help="Source repository or package name.")
    skills_add.add_argument("--source-owner-url", default="", help="Source owner URL.")
    skills_add.add_argument("--source-owner-icon-url", default="", help="Source owner icon URL.")
    skills_add.add_argument("--source-url", default="", help="Source URL.")
    skills_add.add_argument("--install-url", default="", help="Install/source URL.")
    skills_add.add_argument("--website-url", default="", help="Website or docs URL.")
    skills_add.add_argument("--repository-url", default="", help="Repository URL.")
    skills_import = skills_subparsers.add_parser(
        "import-github",
        help="Search and stream matching GitHub repositories into the skills catalog.",
    )
    add_import_github_arguments(skills_import)
    skills_refresh = skills_subparsers.add_parser(
        "refresh",
        help=(
            "Refresh snapshot bundles for all active GitHub skills from their recorded "
            "repository locations."
        ),
    )
    skills_refresh.add_argument(
        "--github-token",
        default="",
        help=f"GitHub token override. Defaults to ${GITHUB_TOKEN_ENV} when set.",
    )
    skills_refresh.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_IMPORT_TIMEOUT_SECONDS,
        help="GitHub request timeout in seconds.",
    )
    skills_audit = skills_subparsers.add_parser(
        "audit",
        help="Audit every unaudited current public skill snapshot.",
    )
    add_audit_arguments(skills_audit)
    skills_official = skills_subparsers.add_parser(
        "mark-official",
        help="Mark a source owner as official.",
    )
    skills_official.add_argument("owner", help="Skill owner, for example vercel-labs.")
    skills_official.add_argument(
        "--source-type",
        default="github",
        choices=["github", "well-known"],
        help="Skill source type.",
    )
    skills_official.add_argument("--owner-url", default="", help="Official owner URL.")
    skills_official.add_argument("--owner-icon-url", default="", help="Official owner icon URL.")
    skills_official.add_argument(
        "--unset",
        action="store_true",
        help="Remove official status from the source owner.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the management CLI version.",
    )
    args = parser.parse_args(argv)
    if args.version:
        print("wardn-hub manage 0.1.0")
    elif args.command == "seed-categories":
        return asyncio.run(seed_categories())
    elif args.command == "skills" and args.skills_command == "add":
        return asyncio.run(add_skill_from_args(args))
    elif args.command == "skills" and args.skills_command == "import-github":
        try:
            configure_logging()
            return run_import_github_command(args, importer=import_github_from_args)
        except SkillCliError as exc:
            parser.error(str(exc))
    elif args.command == "skills" and args.skills_command == "refresh":
        configure_logging()
        return run_refresh_github_command(args)
    elif args.command == "skills" and args.skills_command == "audit":
        try:
            configure_logging()
            return audit_skills_from_args(args)
        except UserFacingError as exc:
            parser.error(str(exc))
    elif args.command == "skills" and args.skills_command == "mark-official":
        return asyncio.run(mark_official_from_args(args))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
