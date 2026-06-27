import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.modules.events.exceptions import EventValidationError

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def generate_signing_secret() -> str:
    return secrets.token_urlsafe(32)


def signing_secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def sign_webhook_payload(raw_body: bytes, secret: str, *, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    message = str(timestamp).encode("ascii") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_webhook_signature(
    raw_body: bytes,
    secret: str,
    signature: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> bool:
    parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now or int(time.time())) - timestamp) > tolerance_seconds:
        return False
    expected = sign_webhook_payload(raw_body, secret, timestamp=timestamp)
    return hmac.compare_digest(expected, signature)


def redacted_url(url: str) -> str:
    parsed = urlsplit(url)
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address in BLOCKED_IPS
    )


def resolved_ip_addresses(hostname: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return addresses
    for result in results:
        sockaddr = result[4]
        if not sockaddr:
            continue
        raw_address = str(sockaddr[0]).split("%", 1)[0]
        try:
            addresses.add(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    return addresses


def validate_webhook_url(url: str, *, allow_private: bool = False) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EventValidationError("webhook URL must be an http or https URL")
    hostname = parsed.hostname.strip().lower()
    if hostname in BLOCKED_HOSTNAMES and not allow_private:
        raise EventValidationError("private webhook destinations are not allowed")
    if hostname in BLOCKED_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        resolved_addresses = resolved_ip_addresses(hostname)
        has_blocked_address = any(_is_blocked_ip(item) for item in resolved_addresses)
        if has_blocked_address and not allow_private:
            raise EventValidationError("private webhook destinations are not allowed") from None
        return has_blocked_address
    if _is_blocked_ip(address) and not allow_private:
        raise EventValidationError("private webhook destinations are not allowed")
    return _is_blocked_ip(address)
