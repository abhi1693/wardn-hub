import argparse
import asyncio

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
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
