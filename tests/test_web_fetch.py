# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""The guarded web fetcher (ADR-030): allowlist, address checks, pinning, redirects, caps."""

import asyncio

import httpx
import pytest

from eka.adapters.web_fetch import SafeFetcher, is_public
from eka.domain.errors import WebFetchRefused
from eka.domain.models import WebPage

HOST = "docs.example.org"
PUBLIC = "93.184.216.34"
HTML = "<html><head><title>T</title></head><body><p>Hello</p></body></html>"


def resolver(table: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return table.get(host, [])

    return resolve


def fetcher(handler, table=None, **kwargs) -> SafeFetcher:  # type: ignore[no-untyped-def]
    return SafeFetcher(
        kwargs.pop("hosts", [HOST, "other.example.org"]),
        max_bytes=kwargs.pop("max_bytes", 10_000),
        timeout_seconds=kwargs.pop("timeout_seconds", 5.0),
        resolver=resolver(
            {HOST: [PUBLIC], "other.example.org": ["93.184.216.35"]} if table is None else table
        ),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def html_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=HTML)


async def refused(f: SafeFetcher, url: str) -> str:
    with pytest.raises(WebFetchRefused) as caught:
        await f.fetch(url)
    return caught.value.reason


@pytest.mark.anyio
async def test_connects_to_the_checked_address_and_keeps_the_host_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return html_response(request)

    page = await fetcher(handler).fetch(f"https://{HOST}/guide/intro.html?v=2")
    assert page == WebPage(f"https://{HOST}/guide/intro.html?v=2", "text/html", HTML)
    (request,) = seen
    assert request.url.host == PUBLIC and request.url.path == "/guide/intro.html"
    assert request.url.query == b"v=2"
    assert request.headers["host"] == HOST
    assert request.extensions["sni_hostname"] == HOST
    assert "cookie" not in request.headers and "authorization" not in request.headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (f"http://{HOST}/", "not_https"),
        (f"https://user:pw@{HOST}/", "user_info"),
        ("https://evil.example.com/", "host_not_allowed"),
        (f"https://sub.{HOST}/", "host_not_allowed"),
        (f"https://{HOST}.evil.com/", "host_not_allowed"),
        ("https://93.184.216.34/", "host_not_allowed"),
        ("https://[::1/", "bad_url"),
    ],
)
async def test_urls_outside_the_policy_are_refused(url: str, reason: str) -> None:
    assert await refused(fetcher(html_response), url) == reason


@pytest.mark.anyio
@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.5"],
        ["127.0.0.1"],
        ["169.254.169.254"],  # cloud metadata
        ["192.168.1.1"],
        ["100.64.0.1"],  # shared address space
        ["::1"],
        ["fd00::1"],
        ["::ffff:10.0.0.1"],  # IPv4-mapped private
        [PUBLIC, "10.0.0.5"],  # one private answer is enough
    ],
)
async def test_a_name_that_resolves_to_a_private_address_is_refused(addresses: list[str]) -> None:
    f = fetcher(html_response, {HOST: addresses})
    assert await refused(f, f"https://{HOST}/") == "private_address"


def test_public_addresses_are_recognised() -> None:
    assert is_public(PUBLIC) and is_public("2606:4700:4700::1111")
    assert not is_public("224.0.0.1") and not is_public("0.0.0.0")


@pytest.mark.anyio
async def test_a_name_that_does_not_resolve_is_refused() -> None:
    assert await refused(fetcher(html_response, {}), f"https://{HOST}/") == "dns"


@pytest.mark.anyio
async def test_a_redirect_inside_the_allowlist_is_followed_and_rechecked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == HOST:
            return httpx.Response(301, headers={"location": "https://other.example.org/new"})
        assert request.url.host == "93.184.216.35"
        return html_response(request)

    page = await fetcher(handler).fetch(f"https://{HOST}/old")
    assert page.url == "https://other.example.org/new"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("location", "table", "reason"),
    [
        ("https://evil.example.com/", None, "host_not_allowed"),
        (f"http://{HOST}/plain", None, "not_https"),
        (
            "https://other.example.org/",
            {HOST: [PUBLIC], "other.example.org": ["10.1.1.1"]},
            "private_address",
        ),
    ],
)
async def test_a_redirect_that_leaves_the_policy_is_refused(
    location: str, table: dict[str, list[str]] | None, reason: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    assert await refused(fetcher(handler, table), f"https://{HOST}/") == reason


@pytest.mark.anyio
async def test_redirect_loops_stop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    assert await refused(fetcher(handler), f"https://{HOST}/") == "too_many_redirects"


@pytest.mark.anyio
async def test_large_bodies_are_refused_whether_declared_or_streamed() -> None:
    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html", "content-length": "999999"}, text="x"
        )

    def streamed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="x" * 20_000)

    assert await refused(fetcher(declared), f"https://{HOST}/") == "too_large"
    assert await refused(fetcher(streamed), f"https://{HOST}/") == "too_large"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "content_type", "reason"),
    [
        (200, "application/pdf", "content_type"),
        (200, "image/svg+xml", "content_type"),
        (404, "text/html", "http_404"),
        (500, "text/html", "http_500"),
    ],
)
async def test_only_successful_text_pages_are_accepted(
    status: int, content_type: str, reason: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": content_type}, text="x")

    assert await refused(fetcher(handler), f"https://{HOST}/") == reason


@pytest.mark.anyio
async def test_the_whole_fetch_has_a_time_limit() -> None:
    async def slow(host: str, port: int) -> list[str]:
        await asyncio.sleep(5)
        return [PUBLIC]

    f = SafeFetcher(
        [HOST],
        max_bytes=1000,
        timeout_seconds=0.05,
        resolver=slow,
        transport=httpx.MockTransport(html_response),
    )
    assert await refused(f, f"https://{HOST}/") == "timeout"


@pytest.mark.anyio
async def test_network_errors_become_a_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert await refused(fetcher(handler), f"https://{HOST}/") == "network"
