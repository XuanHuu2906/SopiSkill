"""P4.2 — outbound URL fetcher có chống SSRF (server-side only).

Cổng bảo mật (theo thứ tự, mọi hop redirect đều phải qua lại từ đầu):

  1. **Cờ + allowlist**: `WEB_INGEST_ENABLED` phải bật VÀ host phải nằm trong
     `WEB_INGEST_ALLOWED_HOSTS`. Allowlist rỗng ⇒ từ chối tất cả (fail closed).
  2. **Scheme/port**: chỉ HTTPS (cấu hình được), port phải là 443 (hoặc rỗng).
     Từ chối URL có userinfo (`https://user:pass@host/`).
  3. **DNS + IP**: resolve hostname TRƯỚC, và **mọi** địa chỉ trả về phải là
     global-unicast. Loopback/private/link-local/metadata/CGNAT/reserved ⇒ từ
     chối cả hostname (không "thử cái khác").
  4. **DNS rebinding**: kết nối TCP được thực hiện qua `PinnedNetworkBackend`
     — backend tự resolve lại ngay tại thời điểm connect và chỉ mở socket tới
     địa chỉ đã kiểm tra global. TLS vẫn dùng SNI/hostname gốc nên chứng chỉ
     được xác thực theo hostname, không theo IP.
  5. **Redirect thủ công**: `follow_redirects=False`; mỗi Location được resolve
     lại và **chạy lại toàn bộ cổng 1–4**. Không có đường tắt sang host khác.
  6. **Trần tài nguyên**: byte/redirect/char/thời gian; vượt ⇒ lỗi mã ổn định,
     không stream tiếp.
  7. **robots.txt**: nếu bật `WEB_INGEST_RESPECT_ROBOTS` thì kiểm tra trước khi
     tải; robots 4xx ⇒ coi như không có luật (allow), 5xx/lỗi mạng ⇒ **từ chối**
     (conservative). Cache trong RAM theo host.

Không log URL đầy đủ (có thể chứa token/query riêng tư), chỉ log host + mã lỗi.
Không lưu nội dung ra log. Không có proxy env: `trust_env=False`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

HTTP_METHOD = "GET"
# Port mặc định của các scheme hiểu được; scheme khác (ftp/file/...) bị từ chối.
DEFAULT_PORTS = {"https": 443, "http": 80}
ALLOWED_SCHEMES = frozenset(DEFAULT_PORTS)
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
PDF_MEDIA_TYPE = "application/pdf"
PLAIN_MEDIA_TYPES = frozenset({"text/plain"})
# `kind="text"`: XML/Atom/JSON metadata. Chỉ nhận text hoặc XML media type —
# không nhận binary lạ để tránh parse nhầm.
TEXT_MEDIA_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/xml",
        "application/rss+xml",
        "application/json",
    }
)
TEXT_KINDS = ("html", "pdf", "text")


class WebFetchError(Exception):
    """Lỗi fetch có mã ổn định và thông điệp an toàn cho người dùng."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass
class FetchedResource:
    requested_url: str
    final_url: str
    http_status: int
    media_type: str
    data: bytes
    retrieved_at: datetime
    content_type_header: str | None = None
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def byte_size(self) -> int:
        return len(self.data)


# ---------- URL + host + IP guard ----------


def parse_http_url(raw: str) -> tuple[str, str, int]:
    """Trả `(scheme, host, port)`. Không tự "sửa" URL hỏng."""
    value = (raw or "").strip()
    if not value:
        raise WebFetchError("URL_EMPTY", "URL rỗng.")
    if len(value) > 2048:
        raise WebFetchError("URL_TOO_LONG", "URL quá dài (>2048 ký tự).")
    if any(ch in value for ch in ("\n", "\r", "\x00", " ", "\t")):
        raise WebFetchError("URL_INVALID_CHARS", "URL chứa ký tự không hợp lệ.")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise WebFetchError("URL_INVALID", "URL không hợp lệ.") from exc

    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not scheme or not host:
        raise WebFetchError("URL_INVALID", "URL phải có scheme và host.")
    if parts.username or parts.password:
        raise WebFetchError(
            "URL_HAS_USERINFO", "URL không được chứa thông tin đăng nhập."
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise WebFetchError("URL_PORT_INVALID", "URL có port không hợp lệ.") from exc
    return scheme, host, DEFAULT_PORTS.get(scheme, 0) if port is None else port


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    """Khớp CHÍNH XÁC host hoặc subdomain của host trong allowlist.

    `example.com` cho phép `docs.example.com` nhưng KHÔNG cho `evil-example.com`
    hay `example.com.attacker.net`.
    """
    if not allowed:
        return False
    candidate = (host or "").strip().lower().rstrip(".")
    if not candidate:
        return False
    for entry in allowed:
        if candidate == entry or candidate.endswith("." + entry):
            return True
    return False


def ip_is_public(ip: str) -> bool:
    """True chỉ khi IP là global-unicast thật.

    `ipaddress.is_global` đã loại private/loopback/link-local/reserved/unspecified;
    hàm này bổ sung chặn multicast và IPv4-mapped IPv6 (có thể lách kiểm tra).
    """
    text = (ip or "").strip()
    if not text:
        return False
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    # Bỏ zone id (`fe80::1%eth0`) trước khi parse.
    text = text.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return ip_is_public(str(address.ipv4_mapped))
    if address.is_multicast:
        return False
    return bool(address.is_global)


async def resolve_host_ips(host: str) -> list[str]:
    """Resolve hostname → danh sách IP (A + AAAA). Không bịa IP khi lỗi."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise WebFetchError("WEB_DNS_FAILED", "Không phân giải được tên miền.") from exc
    except OSError as exc:
        raise WebFetchError("WEB_DNS_FAILED", "Không phân giải được tên miền.") from exc

    seen: dict[str, None] = {}
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0]:
            seen.setdefault(str(sockaddr[0]), None)
    if not seen:
        raise WebFetchError("WEB_DNS_EMPTY", "Tên miền không có địa chỉ IP.")
    return list(seen)


def check_ips_public(ips: list[str]) -> None:
    """Nếu BẤT KỲ địa chỉ nào không public ⇒ từ chối cả hostname."""
    if not ips:
        raise WebFetchError("WEB_DNS_EMPTY", "Tên miền không có địa chỉ IP.")
    for ip in ips:
        if not ip_is_public(ip):
            raise WebFetchError(
                "WEB_BLOCKED_ADDRESS",
                "Địa chỉ đích nằm trong mạng nội bộ/không công khai nên bị chặn.",
            )


def validate_url(url: str, *, settings: Settings | None = None) -> tuple[str, str, int]:
    """Cổng tĩnh: cờ/allowlist/scheme/port. Không resolve DNS."""
    cfg = settings or get_settings()
    scheme, host, port = parse_http_url(url)

    if not cfg.web_ingest_enabled:
        raise WebFetchError(
            "WEB_INGEST_DISABLED",
            "Tính năng tải nội dung từ URL đang tắt trên server.",
        )
    if not cfg.web_allowed_hosts:
        raise WebFetchError(
            "WEB_ALLOWLIST_EMPTY",
            "Chưa cấu hình danh sách host được phép tải nội dung.",
        )
    if scheme not in ALLOWED_SCHEMES:
        raise WebFetchError("WEB_SCHEME_NOT_ALLOWED", "Scheme URL không được phép.")
    if cfg.web_ingest_require_https and scheme != "https":
        raise WebFetchError("WEB_HTTPS_REQUIRED", "Chỉ chấp nhận URL HTTPS.")
    if port != DEFAULT_PORTS[scheme]:
        raise WebFetchError(
            "WEB_PORT_NOT_ALLOWED", f"Chỉ chấp nhận port {DEFAULT_PORTS[scheme]}."
        )
    if not host_allowed(host, cfg.web_allowed_hosts):
        raise WebFetchError(
            "WEB_HOST_NOT_ALLOWED", "Host của URL không nằm trong danh sách được phép."
        )
    return scheme, host, port


async def validate_url_resolved(url: str, *, settings: Settings | None = None) -> str:
    """Cổng tĩnh + DNS: mọi IP của host phải public. Trả host đã kiểm."""
    _scheme, host, _port = validate_url(url, settings=settings)
    check_ips_public(await resolve_host_ips(host))
    return host


# ---------- DNS-pinned network backend ----------


class PinnedNetworkBackend:
    """`httpcore.AsyncNetworkBackend` chỉ kết nối tới IP đã kiểm tra là public.

    Resolve lại hostname NGAY trong `connect_tcp` (sau bước kiểm tra tĩnh), nên
    kịch bản DNS rebinding (DNS đổi giữa validate và connect) vẫn bị chặn.
    TLS/SNI vẫn do httpcore dùng hostname gốc ⇒ chứng chỉ vẫn xác thực đúng host.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        import httpcore

        ips = await resolve_host_ips(host)
        check_ips_public(ips)
        last_error: Exception | None = None
        for ip in ips:
            try:
                return await self._inner.connect_tcp(
                    host=ip,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError(
            "Không kết nối được tới địa chỉ đã kiểm tra."
        )

    async def connect_unix_socket(self, *args, **kwargs):  # pragma: no cover
        import httpcore

        raise httpcore.ConnectError("Unix socket không được phép.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def build_pinned_transport(*, settings: Settings | None = None):
    """`httpx.AsyncHTTPTransport` với network backend kiểm tra IP tại connect.

    Trả transport đã cấu hình; caller chịu trách nhiệm đóng client.
    """
    import httpx

    transport = httpx.AsyncHTTPTransport(
        retries=0,
        trust_env=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
    )
    pool = getattr(transport, "_pool", None)
    if pool is None or not hasattr(pool, "_network_backend"):
        raise WebFetchError(
            "WEB_FETCHER_UNAVAILABLE",
            "Không cấu hình được bộ tải nội dung an toàn trên server.",
        )
    pool._network_backend = PinnedNetworkBackend(pool._network_backend)
    return transport


# ---------- robots.txt ----------

_robots_cache: dict[str, tuple[float, list[tuple[bool, str]]]] = {}


def clear_robots_cache() -> None:
    """Chỉ dùng cho test/dev."""
    _robots_cache.clear()


def _parse_robots(text: str, user_agent_token: str) -> list[tuple[bool, str]]:
    """Trả danh sách `(allow?, path)` của nhóm khớp user-agent (hoặc `*`)."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []

    def flush() -> None:
        nonlocal agents, rules
        if agents and rules:
            groups.append((agents, rules))
        agents = []
        rules = []

    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if rules:
                flush()
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if not value:
                continue
            rules.append((key == "allow", value))
    flush()

    token = (user_agent_token or "").split("/")[0].strip().lower()
    token_rules: list[tuple[bool, str]] = []
    star_rules: list[tuple[bool, str]] = []
    for group_agents, group_rules in groups:
        if token and any(agent and agent in token for agent in group_agents):
            token_rules.extend(group_rules)
        elif "*" in group_agents:
            star_rules.extend(group_rules)
    return token_rules or star_rules


def robots_allows(rules: list[tuple[bool, str]], path: str) -> bool:
    """Luật dài nhất thắng; cùng độ dài thì `Allow` thắng (chuẩn robots.txt)."""
    target = path or "/"
    best_len = -1
    best_allow = True
    for allow, pattern in rules:
        if not pattern:
            continue
        if pattern == "/" or target.startswith(pattern):
            length = len(pattern)
            if length > best_len or (length == best_len and allow):
                best_len = length
                best_allow = allow
    return best_allow


async def _fetch_robots_rules(origin: str, *, cfg: Settings, transport):
    import httpx

    cached = _robots_cache.get(origin)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    url = origin.rstrip("/") + "/robots.txt"
    timeout = httpx.Timeout(
        cfg.web_robots_timeout_seconds,
        connect=cfg.web_fetch_connect_timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=timeout, trust_env=False, follow_redirects=False
        ) as client:
            async with client.stream(HTTP_METHOD, url, headers={"User-Agent": cfg.web_ingest_user_agent}) as resp:
                if 300 <= resp.status_code < 400:
                    # Redirect robots: conservative — coi như không xác định được luật.
                    raise WebFetchError(
                        "WEB_ROBOTS_UNVERIFIABLE",
                        "Không xác minh được robots.txt (redirect) nên không tải nội dung.",
                    )
                if 400 <= resp.status_code < 500:
                    rules: list[tuple[bool, str]] = []
                elif resp.status_code >= 500:
                    raise WebFetchError(
                        "WEB_ROBOTS_UNAVAILABLE",
                        "Máy chủ robots.txt trả lỗi nên không tải nội dung.",
                    )
                else:
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > cfg.web_robots_max_bytes:
                            break
                        chunks.append(chunk)
                    text = b"".join(chunks).decode("utf-8", "replace")
                    rules = _parse_robots(text, cfg.web_ingest_user_agent)
    except WebFetchError:
        raise
    except Exception as exc:  # noqa: BLE001 — lỗi mạng robots ⇒ conservative deny
        raise WebFetchError(
            "WEB_ROBOTS_UNAVAILABLE",
            "Không kiểm tra được robots.txt nên không tải nội dung.",
        ) from exc

    _robots_cache[origin] = (now + max(0, cfg.web_robots_cache_seconds), rules)
    return rules


async def ensure_robots_allowed(url: str, *, cfg: Settings, transport) -> None:
    if not cfg.web_ingest_respect_robots:
        return
    parts = urlsplit(url)
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    rules = await _fetch_robots_rules(origin, cfg=cfg, transport=transport)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    if not robots_allows(rules, path):
        raise WebFetchError(
            "WEB_ROBOTS_DENIED", "robots.txt của trang này không cho phép tải nội dung."
        )


# ---------- fetch ----------


def _split_media_type(raw: str | None) -> str:
    return (raw or "").split(";", 1)[0].strip().lower()


def _decode_text(data: bytes, media_type_header: str | None) -> str:
    charset = "utf-8"
    for part in (media_type_header or "").split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip('"')
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _looks_like_html(data: bytes) -> bool:
    head = data[:2048].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<body" in head


async def _read_capped(resp, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise WebFetchError(
                "WEB_TOO_LARGE", f"Nội dung vượt giới hạn {max_bytes} bytes."
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_resource(
    url: str,
    *,
    kind: str = "html",
    settings: Settings | None = None,
    transport=None,
) -> FetchedResource:
    """Tải một URL qua đầy đủ cổng bảo mật. `kind` ∈ `html` | `pdf`."""
    import httpx

    cfg = settings or get_settings()
    if kind not in TEXT_KINDS:
        raise WebFetchError("WEB_KIND_INVALID", "Loại nội dung cần tải không hợp lệ.")

    own_transport = transport is None
    if own_transport:
        transport = build_pinned_transport(settings=cfg)

    requested = url.strip()
    redirect_chain: list[str] = []
    current = requested
    retrieved_at = datetime.now(UTC)

    timeout = httpx.Timeout(
        cfg.web_fetch_timeout_seconds,
        connect=cfg.web_fetch_connect_timeout_seconds,
    )
    headers = {
        "User-Agent": cfg.web_ingest_user_agent,
        "Accept": (
            "application/pdf,*/*;q=0.5"
            if kind == "pdf"
            else (
                "application/atom+xml,application/xml;q=0.9,application/json;q=0.8,text/plain;q=0.6"
                if kind == "text"
                else "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5"
            )
        ),
        "Accept-Encoding": "identity",
    }

    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        trust_env=False,
        follow_redirects=False,
        max_redirects=0,
    ) as client:
        try:
            async with asyncio.timeout(cfg.web_fetch_timeout_seconds):
                await validate_url_resolved(current, settings=cfg)
                await ensure_robots_allowed(current, cfg=cfg, transport=transport)

                for _hop in range(max(1, cfg.web_max_redirects) + 1):
                    async with client.stream(HTTP_METHOD, current, headers=headers) as resp:
                        if resp.status_code in REDIRECT_STATUSES:
                            location = resp.headers.get("location")
                            if not location:
                                raise WebFetchError(
                                    "WEB_REDIRECT_NO_LOCATION",
                                    "Máy chủ chuyển hướng nhưng thiếu Location.",
                                )
                            nxt = urljoin(current, location).split("#", 1)[0]
                            redirect_chain.append(nxt)
                            await validate_url_resolved(nxt, settings=cfg)
                            await ensure_robots_allowed(nxt, cfg=cfg, transport=transport)
                            current = nxt
                            continue

                        if resp.status_code == 429:
                            raise WebFetchError(
                                "WEB_RATE_LIMITED",
                                "Trang nguồn giới hạn tần suất; thử lại sau.",
                                retryable=True,
                            )
                        if resp.status_code >= 500:
                            raise WebFetchError(
                                "WEB_UPSTREAM_ERROR",
                                f"Trang nguồn trả lỗi {resp.status_code}.",
                                retryable=True,
                            )
                        if resp.status_code != 200:
                            raise WebFetchError(
                                "WEB_HTTP_ERROR",
                                f"Trang nguồn trả mã {resp.status_code}.",
                                retryable=False,
                            )

                        declared = _split_media_type(resp.headers.get("content-type"))
                        content_type_header = resp.headers.get("content-type")
                        length_header = resp.headers.get("content-length")
                        if length_header and length_header.isdigit():
                            if int(length_header) > cfg.web_max_fetch_bytes:
                                raise WebFetchError(
                                    "WEB_TOO_LARGE",
                                    f"Nội dung vượt giới hạn {cfg.web_max_fetch_bytes} bytes.",
                                )
                        data = await _read_capped(resp, cfg.web_max_fetch_bytes)

                        if kind == "pdf":
                            if declared not in (PDF_MEDIA_TYPE, "application/octet-stream"):
                                raise WebFetchError(
                                    "WEB_UNEXPECTED_CONTENT_TYPE",
                                    "URL không trả về PDF như khai báo.",
                                )
                            if not data[:1024].lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"%PDF-"):
                                raise WebFetchError(
                                    "WEB_NOT_PDF", "Nội dung tải về không phải PDF hợp lệ."
                                )
                            media_type = PDF_MEDIA_TYPE
                        elif kind == "text":
                            if declared and declared not in (
                                TEXT_MEDIA_TYPES | PLAIN_MEDIA_TYPES | HTML_MEDIA_TYPES
                            ):
                                raise WebFetchError(
                                    "WEB_UNEXPECTED_CONTENT_TYPE",
                                    "URL không trả về metadata dạng văn bản/XML.",
                                )
                            media_type = declared or "application/xml"
                        else:
                            if declared and declared not in HTML_MEDIA_TYPES | PLAIN_MEDIA_TYPES:
                                raise WebFetchError(
                                    "WEB_UNEXPECTED_CONTENT_TYPE",
                                    "URL không trả về trang HTML văn bản.",
                                )
                            if not _looks_like_html(data):
                                raise WebFetchError(
                                    "WEB_UNEXPECTED_CONTENT_TYPE",
                                    "Nội dung tải về không phải HTML.",
                                )
                            media_type = declared or "text/html"

                        return FetchedResource(
                            requested_url=requested,
                            final_url=current,
                            http_status=resp.status_code,
                            media_type=media_type,
                            data=data,
                            retrieved_at=retrieved_at,
                            content_type_header=content_type_header,
                            redirect_chain=list(redirect_chain),
                        )

                raise WebFetchError(
                    "WEB_TOO_MANY_REDIRECTS",
                    f"URL chuyển hướng quá {cfg.web_max_redirects} lần.",
                )
        except WebFetchError:
            raise
        except TimeoutError as exc:
            raise WebFetchError(
                "WEB_TIMEOUT", "Quá thời gian tải nội dung từ URL.", retryable=True
            ) from exc
        except httpx.TimeoutException as exc:
            raise WebFetchError(
                "WEB_TIMEOUT", "Quá thời gian tải nội dung từ URL.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise WebFetchError(
                "WEB_FETCH_FAILED",
                "Không tải được nội dung từ URL.",
                retryable=True,
            ) from exc
        finally:
            if own_transport:
                try:
                    await transport.aclose()
                except Exception:  # noqa: BLE001 — đóng transport best-effort
                    pass


def decode_html(data: bytes, media_type_header: str | None = None) -> str:
    return _decode_text(data, media_type_header)
