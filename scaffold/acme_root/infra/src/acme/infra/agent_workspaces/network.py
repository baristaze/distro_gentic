"""What a command takes of its host's network: the proxy the host goes
through and the CA file it trusts. Behind a forced or intercepting proxy, a
host reaches the outside only through both, so a command without them
cannot fetch or push. Under open egress a command sees them, and nothing
else of its host's environment. Under any other egress it sees none of
them, since a proxy would open what the egress keeps closed.

A proxy reaches a command as its scheme, host, and port alone: a credential
in its URL stays the host's. A proxy on the host's loopback reaches a local
command alone: inside a container, the loopback is the container's own. The
CA file is read once, when the host starts, so one it cannot read stops it
there, never a session's prepare. A secret never lands in one of these
variables (`ReservedVariable`), so none redirects a command's traffic or
changes what it trusts."""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from acme.infra.exceptions import InfraException
from acme.infra.workspaces import EgressMode

PROXY_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
"""The variables that name a proxy, each by a URL."""

PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})

NO_PROXY_VARIABLES = ("NO_PROXY", "no_proxy")
"""The variables that name what is reached without the proxy."""

CA_FILE_VARIABLE = "SSL_CERT_FILE"
"""The variable that names the CA file a host trusts."""

CA_VARIABLES = (
    CA_FILE_VARIABLE,
    "GIT_SSL_CAINFO",
    "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
"""The variables that name that file to a command: OpenSSL's, and the ones
git, curl, Python's `requests`, and Node read in its place."""

HOST_NETWORK_VARIABLES = frozenset((*PROXY_VARIABLES, *NO_PROXY_VARIABLES, *CA_VARIABLES))
"""Every variable the host's network holds in a command's environment."""


class CAFileUnreadable(InfraException):
    """The CA file the host's environment names cannot be read: the host
    does not start."""

    code = "ca_file_unreadable"


def proxy_address(value: str) -> str | None:
    """The proxy a URL names, as its scheme, host, and port alone; None when
    it names no proxy a client can use."""
    try:
        parts = urlsplit(value)
        if parts.scheme not in PROXY_SCHEMES or not parts.hostname:
            return None
        _ = parts.port  # a port that is not a number raises
    except ValueError:
        return None
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def on_loopback(address: str) -> bool:
    """Whether a proxy's address is on the host's loopback."""
    host = urlsplit(address).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class HostNetwork:
    """The host's proxy and CA file, as its environment names them when it
    starts, with the CA file's content as it read it then."""

    proxies: tuple[tuple[str, str], ...] = ()  # each proxy variable, and its address
    no_proxy: tuple[tuple[str, str], ...] = ()  # each no-proxy variable, as the host has it
    ca_file: Path | None = None
    ca: bytes | None = None  # the CA file's content

    @classmethod
    def of(cls, environ: Mapping[str, str]) -> Self:
        """What `environ` names: each proxy a client can use, stripped of its
        credential; the destinations reached without one; the CA file, and
        its content. A CA file that cannot be read raises
        `CAFileUnreadable`."""
        proxies = tuple(
            (name, address)
            for name in PROXY_VARIABLES
            if (address := proxy_address(environ.get(name, ""))) is not None
        )
        no_proxy = tuple((name, environ[name]) for name in NO_PROXY_VARIABLES if environ.get(name))
        named = environ.get(CA_FILE_VARIABLE)
        if not named:
            return cls(proxies, no_proxy)
        ca_file = Path(named).absolute()
        try:
            ca = ca_file.read_bytes()
        except OSError as error:
            raise CAFileUnreadable(f"{CA_FILE_VARIABLE} names {ca_file}: {error}") from error
        return cls(proxies, no_proxy, ca_file, ca)

    @property
    def loopback(self) -> tuple[str, ...]:
        """The proxy variables that name a proxy on the host's loopback."""
        return tuple(name for name, address in self.proxies if on_loopback(address))

    def in_container(self) -> Self:
        """This network as a container sees it: no proxy on the host's
        loopback, which inside a container is the container itself."""
        kept = tuple((name, address) for name, address in self.proxies if not on_loopback(address))
        return replace(self, proxies=kept)

    def variables(self, egress: EgressMode, ca_path: str | None = None) -> dict[str, str]:
        """What a command under `egress` sees of the host's network: under
        open egress, the proxy and the CA file, at `ca_path` where the
        command reads it there (the host's own path by default); under any
        other, nothing."""
        if egress is not EgressMode.OPEN:
            return {}
        seen = dict(self.proxies) | dict(self.no_proxy)
        if self.ca_file is not None:
            seen |= dict.fromkeys(CA_VARIABLES, ca_path or str(self.ca_file))
        return seen


NO_HOST_NETWORK = HostNetwork()
"""The network of a host that names no proxy and no CA file: what a
transport or a provider hands a command unless it is given the host's."""
