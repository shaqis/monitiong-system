import socket

import httpx
import pytest

from app.worker import prober
from app.worker.prober import (
    MAX_ERROR_MESSAGE_LENGTH,
    ProbeTarget,
    inspect_ssl_days,
    probe,
)


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
