"""A workspace's egress: a project's allowlist, which names destinations and
the methods each takes, open egress as a choice recorded with its reason,
and the answer one request gets. Egress opens outward only: nothing here
opens a way in."""

from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, ClassVar, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from acme.om.base import Identifiable, Platform, Trackable


class EgressMethod(StrEnum):
    """What a request does at its destination, as the egress proxy reads it."""

    GET = "GET"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


READ_ONLY: tuple[EgressMethod, ...] = (EgressMethod.GET, EgressMethod.HEAD, EgressMethod.OPTIONS)
"""The methods that change nothing at their destination: a package
registry's, through its vetting mirror."""

Destination = Annotated[
    str,
    StringConstraints(
        max_length=253,
        pattern=r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$",
    ),
]
"""A host by its name, in lower case, or `*.` and a domain for every host
below it. Never an address, and never a bare name such as `localhost`: an
allowlist names services, and the address a name resolves to is checked on
its own (`rules.egress_decision`)."""


class EgressRule(Platform):
    """One destination, its port, and the methods it takes."""

    destination: Destination
    port: int = Field(default=443, ge=1, le=65535)
    methods: tuple[EgressMethod, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _each_method_once(self) -> Self:
        if len(set(self.methods)) != len(self.methods):
            raise ValueError("a rule names each method once")
        return self


class EgressAllowlist(Identifiable, Trackable):
    """A project's egress, one row a project: its rules, or open egress,
    chosen on purpose and recorded with its reason and who chose it. A
    session takes it when it is created and keeps that copy
    (`SessionWorkspace`), so a later write reaches only later sessions."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("version",)

    project_id: UUID
    rules: tuple[EgressRule, ...] = ()
    open: bool = False  # egress to anywhere but the platform's insides
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _open_is_a_recorded_choice(self) -> Self:
        if self.open and (self.reason is None or self.rules):
            raise ValueError("open egress names its reason, and no rule beside it")
        if not self.open and self.reason is not None:
            raise ValueError("only open egress carries a reason")
        named = [(rule.destination, rule.port) for rule in self.rules]
        if len(set(named)) != len(named):
            raise ValueError("an allowlist names each destination and port once")
        return self


class EgressRequest(Platform):
    """One connection a workspace opens, as the egress proxy sees it: the
    name it asked for, the address that name resolved to, the port, and the
    method, None when the proxy cannot read one."""

    destination: str = Field(min_length=1, max_length=253)
    address: IPv4Address | IPv6Address
    port: int = Field(ge=1, le=65535)
    method: EgressMethod | None = None


class EgressDecision(Platform):
    allowed: bool
    reason: str
