import re

GITHUB_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def normalize_github_username(value: str) -> str:
    username = value.strip()
    if not GITHUB_USERNAME_PATTERN.fullmatch(username):
        return ""
    return username.casefold()


def github_namespace_for_username(username: str) -> str:
    normalized = normalize_github_username(username)
    return f"io.github.{normalized}" if normalized else ""
