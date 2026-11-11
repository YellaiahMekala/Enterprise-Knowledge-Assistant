"""Fetch a page from an allowlisted HTTPS site without opening an SSRF hole (ADR-030).

Each hop (the first URL and every redirect) is checked the same way: https only, no user info,
the exact hostname in the allowlist, and every address the name resolves to must be public. The
connection then goes to the checked address, so a second DNS answer cannot point it elsewhere;
TLS still verifies the certificate for the hostname. Proxies from the environment are ignored for
the same reason. Size, total time and content type are capped. No cookies or credentials are
sent.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urljoin, urlsplit

import httpx

from eka.domain.errors import WebFetchRefused as FetchRefused
from eka.domain.models import WebPage

# (host, port) -> addresses. Tests pass a fake; the default asks the system resolver.
Resolver = Callable[[str, int], Awaitable[list[str]]]

_REDIRECTS = {301, 302, 303, 307, 308}
_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
_USER_AGENT = "eka-web-fallback/1.0"


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global is False for private, loopback, link-local (169.254.169.254 included), shared,
    # reserved and documentation ranges; multicast is excluded separately.
    return ip.is_global and not ip.is_multicast


class SafeFetcher:
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        max_bytes: int,
        timeout_seconds: float,
        max_redirects: int = 3,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allowed = frozenset(host.lower() for host in allowed_hosts)
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._transport = transport

    def check_url(self, url: str) -> tuple[str, int, str]:
        """``(host, port, path with query)`` if the URL may be fetched; raises otherwise."""
        try:
            parts = urlsplit(url)
            port = parts.port or 443
        except ValueError as error:
            raise FetchRefused("bad_url") from error
        if parts.scheme != "https":
            raise FetchRefused("not_https")
        if parts.username or parts.password:
            raise FetchRefused("user_info")
        host = (parts.hostname or "").lower()
        if host not in self._allowed:
            raise FetchRefused("host_not_allowed")
        path = parts.path or "/"
        return host, port, f"{path}?{parts.query}" if parts.query else path

    async def fetch(self, url: str) -> WebPage:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._follow(url)
        except TimeoutError as error:
            raise FetchRefused("timeout") from error
        except httpx.HTTPError as error:
            raise FetchRefused("network") from error

    async def _follow(self, url: str) -> WebPage:
        async with httpx.AsyncClient(
            transport=self._transport, follow_redirects=False, trust_env=False, timeout=None
        ) as client:
            for _ in range(self._max_redirects + 1):
                host, port, target = self.check_url(url)
                address = await self._public_address(host, port)
                literal = f"[{address}]" if ":" in address else address
                request = client.build_request(
                    "GET",
                    f"https://{literal}:{port}{target}",
                    headers={
                        "Host": host if port == 443 else f"{host}:{port}",
                        "User-Agent": _USER_AGENT,
                        "Accept": "text/html, text/plain;q=0.8",
                    },
                    extensions={"sni_hostname": host},
                )
                response = await client.send(request, stream=True)
                try:
                    if response.status_code in _REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchRefused("bad_redirect")
                        url = urljoin(url, location)
                        continue
                    return await self._read(url, response)
                finally:
                    await response.aclose()
        raise FetchRefused("too_many_redirects")

    async def _public_address(self, host: str, port: int) -> str:
        try:
            addresses = await self._resolver(host, port)
        except OSError as error:
            raise FetchRefused("dns") from error
        if not addresses:
            raise FetchRefused("dns")
        # One private answer is enough to refuse: the name is not under the owner's control.
        if not all(is_public(address) for address in addresses):
            raise FetchRefused("private_address")
        return addresses[0]

    async def _read(self, url: str, response: httpx.Response) -> WebPage:
        if response.status_code != 200:
            raise FetchRefused(f"http_{response.status_code}")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in _CONTENT_TYPES:
            raise FetchRefused("content_type")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            raise FetchRefused("too_large")
        body = bytearray()
        async for piece in response.aiter_bytes():
            body.extend(piece)
            if len(body) > self._max_bytes:
                raise FetchRefused("too_large")
        text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
        return WebPage(url=url, content_type=content_type, text=text)
