import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the management CLI version.",
    )
    args = parser.parse_args(argv)
    if args.version:
        print("wardn-hub manage 0.1.0")
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

