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
MAX_KEYWORD_BODY_BYTES = 1_048_576
KEYWORD_CHUNK_SIZE = 64 * 1024

SSL_CERT_TIME_FORMAT = "%b %d %H:%M:%S %Y %Z"
SECONDS_PER_DAY = 86400

# One context avoids rebuilding the trust store for every inspection.
_SSL_CONTEXT = ssl.create_default_context()


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


def _failed(message: str | None) -> ProbeResult:
    return ProbeResult(
        ok=False,
        status_code=None,
        response_time_ms=None,
        keyword_matched=None,
        error_message=_bounded(message),
        ssl_days_remaining=None,
    )


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
        with socket.create_connection((host, port), timeout=timeout_seconds) as raw_socket:
            with _SSL_CONTEXT.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
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
        # The wall-clock budget covers redirects, headers, and the body read.
        async with asyncio.timeout(target.timeout_seconds):
            async with client.stream(
                target.http_method.upper(),
                target.url,
                headers={"User-Agent": user_agent},
                timeout=target.timeout_seconds,
                follow_redirects=True,
            ) as response:
                status_code = response.status_code
                final_url = str(response.url)

                keyword_matched: bool | None = None
                if target.keyword is not None:
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=KEYWORD_CHUNK_SIZE):
                        body.extend(chunk)
                        if len(body) >= MAX_KEYWORD_BODY_BYTES:
                            del body[MAX_KEYWORD_BODY_BYTES:]
                            break
                    keyword_matched = target.keyword.encode("utf-8") in body

                response_time_ms = int((time.perf_counter() - started_at) * 1000)
    except TimeoutError:
        return _failed(f"Request timed out after {target.timeout_seconds}s")
    except httpx.TimeoutException:
        return _failed(f"Request timed out after {target.timeout_seconds}s")
    except httpx.ConnectError as exc:
        return _failed(f"Connection failed: {exc}")
    except httpx.HTTPError as exc:
        return _failed(f"HTTP error: {exc}")
    except ssl.SSLError as exc:
        return _failed(f"TLS error: {exc}")
    except socket.gaierror as exc:
        return _failed(f"DNS lookup failed: {exc}")
    except Exception as exc:
        return _failed(f"Probe failed: {type(exc).__name__}: {exc}")

    status_ok = _status_matches(target.expected_status_code, status_code)
    error_message: str | None = None
    if not status_ok:
        error_message = f"Expected {target.expected_status_code}, got {status_code}"
    elif keyword_matched is False:
        error_message = f"Keyword {target.keyword!r} not found in first 1 MiB of response body"

    ssl_days_remaining: int | None = None
    if target.check_ssl and final_url.startswith("https://"):
        ssl_days_remaining = await _ssl_days_remaining(final_url, ssl_inspect_timeout_seconds)

    return ProbeResult(
        ok=status_ok and keyword_matched is not False,
        status_code=status_code,
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
