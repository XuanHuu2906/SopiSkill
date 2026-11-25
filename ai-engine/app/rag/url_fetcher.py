"""SSRF-safe outbound URL fetcher for `ai-worker-ingest` (fail-closed allowlist + DNS global IP guard)."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings, get_settings

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class WebFetchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FetchedResource:
    final_url: str
    media_type: str
    data: bytes


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return False
    candidate = (host or "").strip().lower().rstrip(".")
    if not candidate:
        return False
    return any(candidate == entry or candidate.endswith("." + entry) for entry in allowed)


def _validate_ip(raw_ip: str) -> None:
    addr = ipaddress.ip_address(raw_ip)
    if not addr.is_global or addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        raise WebFetchError("SSRF_BLOCKED_IP", "Target resolved to a non-global IP address.")


def validate_outbound_url(raw_url: str, *, settings: Settings | None = None, resolve_dns: bool = True) -> tuple[str, str, int]:
    cfg = settings or get_settings()
    if not cfg.web_ingest_enabled:
        raise WebFetchError("WEB_INGEST_DISABLED", "Web ingestion is disabled by configuration.")

    value = (raw_url or "").strip()
    if not value or len(value) > 2048 or any(c in value for c in ("\n", "\r", "\x00", " ", "\t")):
        raise WebFetchError("URL_INVALID", "Invalid URL syntax.")

    parts = urlsplit(value)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if scheme != "https" or not host:
        raise WebFetchError("URL_SCHEME_FORBIDDEN", "Only HTTPS URLs with a valid host are allowed.")
    if parts.username or parts.password:
        raise WebFetchError("URL_HAS_USERINFO", "URLs with embedded credentials are forbidden.")

    port = parts.port or 443
    if port != 443:
        raise WebFetchError("URL_PORT_FORBIDDEN", "Only standard HTTPS port 443 is permitted.")

    if not host_allowed(host, cfg.allowed_web_hosts):
        raise WebFetchError("URL_HOST_NOT_ALLOWED", "Host is not in WEB_INGEST_ALLOWED_HOSTS.")

    # Direct IP literal check first
    try:
        _validate_ip(host)
    except ValueError:
        if resolve_dns:
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise WebFetchError("DNS_RESOLUTION_FAILED", "Could not resolve target host.") from exc
            if not infos:
                raise WebFetchError("DNS_RESOLUTION_FAILED", "No DNS records for target host.")
            for info in infos:
                _validate_ip(info[4][0])

    return scheme, host, port


async def fetch_url_safe(
    raw_url: str,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    resolve_dns: bool = True,
) -> FetchedResource:
    cfg = settings or get_settings()
    current_url = raw_url
    max_redirects = max(0, int(cfg.web_ingest_max_redirects))
    max_bytes = max(1024, int(cfg.web_ingest_max_bytes))

    async with httpx.AsyncClient(
        timeout=float(cfg.web_ingest_timeout_seconds),
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    ) as client:
        for _ in range(max_redirects + 1):
            validate_outbound_url(current_url, settings=cfg, resolve_dns=resolve_dns)
            async with client.stream("GET", current_url) as resp:
                if resp.status_code in REDIRECT_STATUSES:
                    location = resp.headers.get("location")
                    if not location:
                        raise WebFetchError("REDIRECT_MISSING_LOCATION", "Redirect missing Location header.")
                    current_url = urljoin(current_url, location)
                    continue
                if resp.status_code >= 400:
                    raise WebFetchError("UPSTREAM_HTTP_ERROR", f"Upstream returned HTTP {resp.status_code}.")

                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise WebFetchError("RESPONSE_TOO_LARGE", "Fetched document exceeded byte limit.")

                media_type = (resp.headers.get("content-type") or "text/plain").split(";")[0].strip().lower()
                return FetchedResource(final_url=current_url, media_type=media_type, data=bytes(buf))

    raise WebFetchError("TOO_MANY_REDIRECTS", "Exceeded maximum redirect hops.")
