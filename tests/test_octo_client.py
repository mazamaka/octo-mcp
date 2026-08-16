"""Tests for the Octo Browser API clients.

Requests are served by httpx.MockTransport, so no Octo Browser and no network
access is needed. Each test asserts the request shape documented at
https://documenter.getpostman.com/view/1801428/UVC6i6eA
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from octo_mcp.octo_client import (
    OctoAPIError,
    OctoCloudClient,
    OctoLocalClient,
    extract_ws_endpoint,
)

Handler = Callable[[httpx.Request], httpx.Response]


def cloud_client(handler: Handler, token: str | None = "test-token") -> OctoCloudClient:
    """Cloud client wired to a mock transport."""
    client = OctoCloudClient(api_token=token)
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
        headers={"X-Octo-Api-Token": token} if token else {},
    )
    return client


def local_client(handler: Handler, host: str = "localhost") -> OctoLocalClient:
    """Local client wired to a mock transport."""
    client = OctoLocalClient(host=host)
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
    )
    return client


def envelope(data: object, status: int = 200) -> httpx.Response:
    """Cloud API success envelope."""
    return httpx.Response(status, json={"success": True, "msg": "", "data": data})


# === Cloud API ===


async def test_get_profile_unwraps_envelope() -> None:
    """Cloud responses are wrapped in {success, msg, data} -- callers get data."""
    handler = lambda request: envelope({"uuid": "abc", "title": "work_US"})  # noqa: E731

    client = cloud_client(handler)
    profile = await client.get_profile("abc")

    assert profile == {"uuid": "abc", "title": "work_US"}


async def test_search_profiles_params() -> None:
    """Tags go to search_tags, page_len snaps to a value the API accepts."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return envelope([{"uuid": "abc", "title": "work_US"}])

    client = cloud_client(handler)
    profiles = await client.search_profiles(search="work", tags=["ads", "us"], page_len=20)

    assert profiles == [{"uuid": "abc", "title": "work_US"}]
    assert seen["search"] == "work"
    assert seen["search_tags"] == "ads,us"
    assert seen["page_len"] == "25"  # 20 is not one of 10/25/50/100
    assert seen["fields"] == "title,status,tags"


async def test_import_cookies_wraps_body() -> None:
    """The endpoint expects {"cookies": [...]}, not a bare array."""
    body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body.update(json.loads(request.content))
        return envelope("")

    client = cloud_client(handler)
    await client.import_cookies("abc", [{"name": "sid", "domain": ".example.com"}])

    assert body == {"cookies": [{"name": "sid", "domain": ".example.com"}]}


async def test_transfer_profiles_body() -> None:
    """The receiver field is receiver_email."""
    body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body.update(json.loads(request.content))
        return envelope("")

    client = cloud_client(handler)
    await client.transfer_profiles(["abc"], "buyer@example.com", transfer_proxy=True)

    assert body == {
        "uuids": ["abc"],
        "receiver_email": "buyer@example.com",
        "transfer_proxy": True,
    }


async def test_create_tag_rejects_hex_color() -> None:
    """The API takes colour names, not hex values."""
    client = cloud_client(lambda request: envelope({}))

    with pytest.raises(ValueError, match="Invalid tag color"):
        await client.create_tag("ads", color="#ff0000")


async def test_team_extensions_paginate() -> None:
    """All pages are fetched, not just the first."""
    pages = {
        0: [{"uuid": f"ext{i}"} for i in range(25)],
        25: [{"uuid": "ext25"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        return envelope(pages.get(start, []))

    client = cloud_client(handler)
    extensions = await client.get_team_extensions()

    assert len(extensions) == 26


async def test_api_error_carries_code() -> None:
    """Failures surface the API message and code."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"success": False, "msg": "Bulk force stop error", "code": "profiles.stop_error"},
        )

    client = cloud_client(handler)

    with pytest.raises(OctoAPIError) as exc:
        await client.force_stop_profiles(["abc"])

    assert exc.value.code == "profiles.stop_error"
    assert exc.value.status_code == 400
    assert "Bulk force stop error" in str(exc.value)


async def test_forbidden_mentions_token() -> None:
    """403 points at the token instead of leaking a raw httpx error."""
    client = cloud_client(lambda request: httpx.Response(403, json={"success": False}))

    with pytest.raises(OctoAPIError, match="OCTO_API_TOKEN"):
        await client.get_tags()


async def test_forbidden_keeps_api_reason() -> None:
    """403 is also returned for an expired subscription -- keep that reason."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "success": False,
                "msg": "No active subscription",
                "code": "subscriptions.inactive",
            },
        )

    client = cloud_client(handler)

    with pytest.raises(OctoAPIError, match="No active subscription"):
        await client.get_tags()


async def test_rate_limit_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 is retried a bounded number of times, never forever."""
    real_sleep = asyncio.sleep
    delays: list[float] = []
    calls = 0

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"success": False})

    client = cloud_client(handler)

    with pytest.raises(OctoAPIError, match="Rate limit"):
        await client.get_tags()

    assert calls == 6  # initial attempt + MAX_RETRIES
    assert delays == [2.0] * 5  # Retry-After is honoured


async def test_missing_token_raises() -> None:
    """No token is a configuration error, not an API error."""
    client = cloud_client(lambda request: envelope([]), token=None)

    with pytest.raises(ValueError, match="OCTO_API_TOKEN"):
        await client.get_tags()


# === Local API ===


async def test_active_profiles_returns_bare_list() -> None:
    """The local API answers with a JSON array, not an envelope."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"uuid": "abc", "state": "STARTED"}])

    client = local_client(handler)
    profiles = await client.get_active_profiles()

    assert profiles == [{"uuid": "abc", "state": "STARTED"}]


async def test_ws_endpoint_rewritten_to_configured_host() -> None:
    """Remote/Docker setups need 127.0.0.1 swapped for the real host."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "uuid": "abc",
                "ws_endpoint": "ws://127.0.0.1:55834/devtools/browser/xyz",
            },
        )

    client = local_client(handler, host="192.168.1.100")
    result = await client.start_profile("abc")

    assert result["ws_endpoint"] == "ws://192.168.1.100:55834/devtools/browser/xyz"


async def test_start_profile_body() -> None:
    """Documented start payload, plus the optional profile password."""
    body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/username"):
            return httpx.Response(200, json={"username": "user@example.com"})
        body.update(json.loads(request.content))
        return httpx.Response(200, json={"uuid": "abc"})

    client = local_client(handler)
    await client.start_profile("abc", headless=True, timeout=90, password="secret")

    assert body == {
        "uuid": "abc",
        "headless": True,
        "debug_port": True,
        "timeout": 90,
        "flags": ["--start-maximized"],
        "only_local": True,
        "password": "secret",
    }


async def test_get_or_start_returns_running_profile_on_start_error() -> None:
    """A profile started elsewhere makes start fail -- fall back to the active list."""
    started = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal started
        path = request.url.path
        if path.endswith("/profiles/active"):
            return httpx.Response(
                200,
                json=[{"uuid": "abc", "ws_endpoint": "ws://127.0.0.1:1/x"}] if started else [],
            )
        if path.endswith("/username"):
            return httpx.Response(200, json={"username": "user@example.com"})
        started = True  # someone else won the race
        return httpx.Response(400, json={"msg": "Profile already running", "code": 2})

    client = local_client(handler)
    result = await client.get_or_start_profile("abc")

    assert result["already_running"] is True
    assert result["uuid"] == "abc"


async def test_get_or_start_reraises_real_failure() -> None:
    """A genuine start failure is not swallowed."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/profiles/active"):
            return httpx.Response(200, json=[])
        if path.endswith("/username"):
            return httpx.Response(200, json={"username": "user@example.com"})
        return httpx.Response(400, json={"msg": "Invalid proxy data", "code": 5})

    client = local_client(handler)

    with pytest.raises(OctoAPIError, match="Invalid proxy data"):
        await client.get_or_start_profile("abc")


async def test_non_json_response_does_not_crash() -> None:
    """An HTML error page from a proxy must not blow up the client."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    client = local_client(handler)

    with pytest.raises(OctoAPIError, match="Bad Gateway"):
        await client.get_version()


async def test_health_check_false_when_unreachable() -> None:
    """An unreachable client API is reported, not raised."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = local_client(handler)

    assert await client.health_check() is False


# === Helpers ===


def test_extract_ws_endpoint_prefers_known_keys() -> None:
    """The endpoint is found in the usual key, and nested if needed."""
    assert extract_ws_endpoint({"ws_endpoint": "ws://host/x"}) == "ws://host/x"
    assert extract_ws_endpoint({"a": {"b": "wss://host/y"}}) == "wss://host/y"
    assert extract_ws_endpoint({"debug_port": "55834"}) is None
