import asyncio
import socket
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator

import httpx
import pytest

from app.worker import prober
from app.worker.prober import (
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_KEYWORD_BODY_BYTES,
    ProbeResult,
    ProbeTarget,
    inspect_ssl_days,
    probe,
)


class _ChunkStream(httpx.AsyncByteStream):
    """Wrap an async byte generator in the interface httpx expects."""

    def __init__(self, chunks: AsyncGenerator[bytes, None]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        await self._chunks.aclose()


class _RaisingStream(httpx.AsyncByteStream):
    """A body stream that fails loudly if anything tries to read it."""

    def __init__(self) -> None:
        self.iterated = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        raise RuntimeError("body should not be read")


class _StreamTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        stream: httpx.AsyncByteStream,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._stream = stream
        self._status_code = status_code
        self._headers = headers

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            self._status_code,
            headers=self._headers,
            stream=self._stream,
        )


async def _probe_stream(
    stream: httpx.AsyncByteStream,
    target: ProbeTarget,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> ProbeResult:
    transport = _StreamTransport(stream, status_code, headers)
    async with httpx.AsyncClient(transport=transport) as client:
        return await probe(target, client=client)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def _probe(handler, target: ProbeTarget, monkeypatch=None):
    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        return await probe(target, client=client)


async def test_default_expected_status_accepts_any_2xx() -> None:
    result = await _probe(
        lambda request: httpx.Response(204),
        ProbeTarget(url="https://example.test", check_ssl=False),
    )

    assert result.ok is True
    assert result.status_code == 204
    assert result.response_time_ms is not None
    assert result.error_message is None


async def test_explicit_expected_status_must_match_exactly() -> None:
    accepted = await _probe(
        lambda request: httpx.Response(204),
        ProbeTarget(url="http://example.test", expected_status_code=204, check_ssl=False),
    )
    rejected = await _probe(
        lambda request: httpx.Response(201),
        ProbeTarget(url="http://example.test", expected_status_code=204, check_ssl=False),
    )

    assert accepted.ok is True
    assert rejected.ok is False
    assert rejected.status_code == 201
    assert rejected.error_message == "Expected 204, got 201"


async def test_keyword_match_and_mismatch() -> None:
    matched = await _probe(
        lambda request: httpx.Response(200, text="hello operator"),
        ProbeTarget(url="http://example.test", keyword="operator", check_ssl=False),
    )
    missing = await _probe(
        lambda request: httpx.Response(200, text="hello operator"),
        ProbeTarget(url="http://example.test", keyword="absent", check_ssl=False),
    )

    assert matched.ok is True
    assert matched.keyword_matched is True
    assert missing.ok is False
    assert missing.keyword_matched is False
    assert missing.error_message is not None
    assert "Keyword 'absent' not found" in missing.error_message


async def test_head_with_keyword_fails_on_empty_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, content=b"")

    result = await _probe(
        handler,
        ProbeTarget(
            url="http://example.test",
            http_method="HEAD",
            keyword="present",
            check_ssl=False,
        ),
    )

    assert result.ok is False
    assert result.keyword_matched is False


async def test_keyword_drip_body_times_out() -> None:
    async def drip() -> AsyncIterator[bytes]:
        for _ in range(200):
            yield b"x"
            await asyncio.sleep(0.05)

    started_at = time.perf_counter()
    result = await _probe_stream(
        _ChunkStream(drip()),
        ProbeTarget(
            url="http://example.test",
            keyword="operator",
            timeout_seconds=1,
            check_ssl=False,
        ),
    )
    elapsed = time.perf_counter() - started_at

    assert result.ok is False
    assert result.status_code is None
    assert result.error_message is not None
    assert "timed out" in result.error_message
    assert elapsed < 2.0


async def test_keyword_beyond_byte_cap_is_not_read() -> None:
    keyword = b"needle"

    async def body() -> AsyncIterator[bytes]:
        yield b"a" * (MAX_KEYWORD_BODY_BYTES // 2)
        yield b"a" * (MAX_KEYWORD_BODY_BYTES // 2)
        yield b"a" * (512 * 1024)
        yield keyword
        yield b"b" * (512 * 1024 - len(keyword))

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="needle", check_ssl=False),
    )

    assert result.ok is False
    assert result.keyword_matched is False


async def test_keyword_inside_the_byte_cap_matches() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"a" * 128
        yield b"needle"
        yield b"a" * (MAX_KEYWORD_BODY_BYTES - 134)

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="needle", check_ssl=False),
    )

    assert result.ok is True
    assert result.keyword_matched is True


async def test_keyword_straddling_the_byte_cap_matches() -> None:
    keyword = b"needle"

    async def body() -> AsyncIterator[bytes]:
        yield b"a" * (MAX_KEYWORD_BODY_BYTES - 3)
        yield keyword
        yield b"b" * 1024

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="needle", check_ssl=False),
    )

    assert result.ok is True
    assert result.keyword_matched is True


async def test_keyword_split_across_chunks_matches() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"status: oper"
        yield b"ator ready"

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="operator", check_ssl=False),
    )

    assert result.ok is True
    assert result.keyword_matched is True


async def test_keyword_matches_a_non_utf8_response() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield "café au lait".encode("iso-8859-1")

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="café", check_ssl=False),
        headers={"Content-Type": "text/plain; charset=iso-8859-1"},
    )

    assert result.ok is True
    assert result.keyword_matched is True


async def test_keyword_none_never_reads_the_body() -> None:
    stream = _RaisingStream()

    result = await _probe_stream(
        stream,
        ProbeTarget(url="http://example.test", check_ssl=False),
    )

    assert result.ok is True
    assert result.status_code == 200
    assert result.keyword_matched is None
    assert stream.iterated is False


async def test_status_mismatch_never_reads_the_body() -> None:
    stream = _RaisingStream()

    result = await _probe_stream(
        stream,
        ProbeTarget(
            url="http://example.test",
            expected_status_code=204,
            keyword="operator",
            check_ssl=False,
        ),
        status_code=500,
    )

    assert result.ok is False
    assert result.status_code == 500
    assert result.keyword_matched is None
    assert stream.iterated is False


async def test_response_time_excludes_the_body_read() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"first"
        await asyncio.sleep(0.3)
        yield b"second"

    result = await _probe_stream(
        _ChunkStream(body()),
        ProbeTarget(url="http://example.test", keyword="absent", check_ssl=False),
    )

    assert result.keyword_matched is False
    assert result.response_time_ms is not None
    assert result.response_time_ms < 250


async def test_timeout_returns_null_status_code_and_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    result = await _probe(
        handler,
        ProbeTarget(url="http://example.test", timeout_seconds=3, check_ssl=False),
    )

    assert result.ok is False
    assert result.status_code is None
    assert result.response_time_ms is None
    assert result.error_message == "Request timed out after 3s"


async def test_connect_error_returns_null_status_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = await _probe(
        handler,
        ProbeTarget(url="http://example.test", check_ssl=False),
    )

    assert result.ok is False
    assert result.status_code is None
    assert result.error_message is not None
    assert result.error_message.startswith("Connection failed")


async def test_dns_error_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise socket.gaierror(-2, "Name or service not known")

    result = await _probe(
        handler,
        ProbeTarget(url="http://missing.example.test", check_ssl=False),
    )

    assert result.ok is False
    assert result.status_code is None
    assert result.error_message is not None
    assert result.error_message.startswith("DNS lookup failed")


async def test_unexpected_error_never_escapes_probe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    result = await _probe(
        handler,
        ProbeTarget(url="http://example.test", check_ssl=False),
    )

    assert result.ok is False
    assert result.status_code is None
    assert result.error_message is not None
    assert "RuntimeError" in result.error_message


async def test_error_message_is_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x" * (MAX_ERROR_MESSAGE_LENGTH * 2), request=request)

    result = await _probe(
        handler,
        ProbeTarget(url="http://example.test", check_ssl=False),
    )

    assert result.error_message is not None
    assert len(result.error_message) == MAX_ERROR_MESSAGE_LENGTH


async def test_ssl_inspection_runs_for_https_targets(monkeypatch) -> None:
    inspected: list[str] = []

    def fake_inspect(url: str, timeout_seconds: float) -> int | None:
        inspected.append(url)
        return 12

    monkeypatch.setattr(prober, "inspect_ssl_days", fake_inspect)

    result = await _probe(
        lambda request: httpx.Response(200, text="ok"),
        ProbeTarget(url="https://example.test", check_ssl=True),
    )

    assert result.ok is True
    assert result.ssl_days_remaining == 12
    assert inspected == ["https://example.test"]


async def test_ssl_inspection_failure_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(prober, "inspect_ssl_days", lambda url, timeout_seconds: None)

    result = await _probe(
        lambda request: httpx.Response(200, text="ok"),
        ProbeTarget(url="https://example.test", check_ssl=True),
    )

    assert result.ok is True
    assert result.ssl_days_remaining is None


async def test_ssl_inspection_timeout_returns_none_without_blocking_the_check(
    monkeypatch,
) -> None:
    release = threading.Event()

    def hanging_inspect(url: str, timeout_seconds: float) -> int | None:
        release.wait(10)
        return 12

    monkeypatch.setattr(prober, "inspect_ssl_days", hanging_inspect)
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            transport=_transport(lambda request: httpx.Response(200, text="ok")),
        ) as client:
            result = await probe(
                ProbeTarget(url="https://example.test", check_ssl=True),
                client=client,
                ssl_inspect_timeout_seconds=0.2,
            )
    finally:
        elapsed = time.perf_counter() - started_at
        release.set()

    assert result.ok is True
    assert result.ssl_days_remaining is None
    assert elapsed < 2.0


async def test_ssl_inspection_skipped_without_response(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        prober,
        "inspect_ssl_days",
        lambda url, timeout_seconds: called.append(url) or 1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    result = await _probe(
        handler,
        ProbeTarget(url="https://example.test", check_ssl=True),
    )

    assert result.ok is False
    assert result.ssl_days_remaining is None
    assert called == []


async def test_ssl_inspection_skipped_when_disabled(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        prober,
        "inspect_ssl_days",
        lambda url, timeout_seconds: called.append(url) or 1,
    )

    result = await _probe(
        lambda request: httpx.Response(200, text="ok"),
        ProbeTarget(url="https://example.test", check_ssl=False),
    )

    assert result.ok is True
    assert result.ssl_days_remaining is None
    assert called == []


def test_inspect_ssl_days_returns_none_on_connection_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "create_connection", fail)

    assert inspect_ssl_days("https://example.test", 0.1) is None


def test_inspect_ssl_days_rejects_non_https_url() -> None:
    assert inspect_ssl_days("http://example.test", 0.1) is None


@pytest.mark.parametrize(
    "url",
    ["http://", "ftp://example.test"],
)
def test_invalid_urls_are_not_ssl_inspected(url: str) -> None:
    assert inspect_ssl_days(url, 0.1) is None
