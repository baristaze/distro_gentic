"""The addresses a cloud connector's name stands for, held to the public
internet at each exchange: a name that resolves to this host or a private
network is refused as an address naming one is (`rules.address_refusal`)."""

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from acme.om.connectors.rules import address_refusal, public

Resolve = Callable[[str], Awaitable[tuple[str, ...]]]
"""The addresses a host name stands for now."""


async def resolve(host: str) -> tuple[str, ...]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


async def refused_now(url: str, *, private: bool, resolver: Resolve) -> str | None:
    """Why the platform's cloud may not call `url` now, or None when it may:
    the address's own refusal, or, for a name, any address it resolves to
    that is not public. A name that does not resolve is refused too."""
    refusal = address_refusal(url, private=private)
    if refusal is not None or private:
        return refusal
    host = urlsplit(url).hostname or ""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None  # an address, held already
    try:
        found = await resolver(host)
    except OSError:
        return f"{host} does not resolve"
    if not found:
        return f"{host} does not resolve"
    for each in found:
        if not public(ipaddress.ip_address(each.split("%", 1)[0])):
            return f"{host} resolves to {each}, which is not a public address"
    return None
