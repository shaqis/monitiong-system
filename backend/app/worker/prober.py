import asyncio
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

DEFAULT_USER_AGENT = "UptimeMonitor/1.0"
DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS = 5.0
MAX_ERROR_MESSAGE_LENGTH = 500

SSL_CERT_TIME_FORMAT = "%b %d %H:%M:%S %Y %Z"
SECONDS_PER_DAY = 86400


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    url: str
    http_method: str = "GET"
    timeout_seconds: int = 10
    expected_status_code: int = 200
    keyword: str | None = None
    check_ssl: bool = True


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    status_code: int | None
    response_time_ms: int | None
    keyword_matched: bool | None
    error_message: str | None
    ssl_days_remaining: int | None


def _bounded(message: str | None) -> str | None:
    if message is None:
        return None
    return message[:MAX_ERROR_MESSAGE_LENGTH]


def _status_matches(expected_status_code: int, actual_status_code: int) -> bool:
    if expected_status_code == 200:
        return 200 <= actual_status_code <= 299
    return actual_status_code == expected_status_code


def inspect_ssl_days(
    url: str,
    timeout_seconds: float = DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
) -> int | None:
    """Return whole days until the peer certificate expires, or None."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host:
            return None

        port = parsed.port or 443
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout_seconds) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                certificate = tls_socket.getpeercert()

        if not certificate:
            return None
        not_after = certificate.get("notAfter")
        if not isinstance(not_after, str):
            return None

        expires_at = datetime.strptime(not_after, SSL_CERT_TIME_FORMAT).replace(tzinfo=UTC)
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        return int(remaining // SECONDS_PER_DAY)
    except Exception:
        return None


async def _ssl_days_remaining(url: str, timeout_seconds: float) -> int | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(inspect_ssl_days, url, timeout_seconds),
            timeout=timeout_seconds + 1.0,
        )
    except Exception:
        return None


async def _execute(
    client: httpx.AsyncClient,
    target: ProbeTarget,
    user_agent: str,
    ssl_inspect_timeout_seconds: float,
) -> ProbeResult:
    started_at = time.perf_counter()
    try:
        response = await client.request(
            target.http_method.upper(),
            target.url,
            headers={"User-Agent": user_agent},
            timeout=target.timeout_seconds,
            follow_redirects=True,
        )
    except httpx.TimeoutException:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"Request timed out after {target.timeout_seconds}s"),
            ssl_days_remaining=None,
        )
    except httpx.ConnectError as exc:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"Connection failed: {exc}"),
            ssl_days_remaining=None,
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"HTTP error: {exc}"),
            ssl_days_remaining=None,
        )
    except ssl.SSLError as exc:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"TLS error: {exc}"),
            ssl_days_remaining=None,
        )
    except socket.gaierror as exc:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"DNS lookup failed: {exc}"),
            ssl_days_remaining=None,
        )
    except Exception as exc:
        return ProbeResult(
            ok=False,
            status_code=None,
            response_time_ms=None,
            keyword_matched=None,
            error_message=_bounded(f"Probe failed: {type(exc).__name__}: {exc}"),
            ssl_days_remaining=None,
        )

    response_time_ms = int((time.perf_counter() - started_at) * 1000)
    status_ok = _status_matches(target.expected_status_code, response.status_code)
    keyword_matched: bool | None = None
    if target.keyword is not None:
        keyword_matched = target.keyword in response.text

    error_message: str | None = None
    if not status_ok:
        error_message = f"Expected {target.expected_status_code}, got {response.status_code}"
    elif keyword_matched is False:
        error_message = f"Keyword {target.keyword!r} not found in response body"

    ssl_days_remaining: int | None = None
    final_url = str(response.url)
    if target.check_ssl and final_url.startswith("https://"):
        ssl_days_remaining = await _ssl_days_remaining(final_url, ssl_inspect_timeout_seconds)

    return ProbeResult(
        ok=status_ok and keyword_matched is not False,
        status_code=response.status_code,
        response_time_ms=response_time_ms,
        keyword_matched=keyword_matched,
        error_message=_bounded(error_message),
        ssl_days_remaining=ssl_days_remaining,
    )


async def probe(
    target: ProbeTarget,
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    ssl_inspect_timeout_seconds: float = DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
) -> ProbeResult:
    """Probe one target. Network failures are reported, never raised."""
    if client is not None:
        return await _execute(client, target, user_agent, ssl_inspect_timeout_seconds)

    async with httpx.AsyncClient(
        follow_redirects=True,
        verify=True,
        timeout=target.timeout_seconds,
    ) as owned_client:
        return await _execute(owned_client, target, user_agent, ssl_inspect_timeout_seconds)
