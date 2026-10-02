"""The gateway's transitions for a workspace host, a client of the gateway
that is no person. A host enrolls with its tenant's enrollment token, and
every later call carries its own credential, whose prefix no other
transition accepts. Its identity comes from that credential alone, so
nothing a host sends names its tenant, its pool, or a lane."""

from typing import Annotated

from fastapi import Depends, Header, Request

from acme.om.hosts.types.host import HostIdentity
from acme.services.api.gateway.admission import READ_METHODS
from acme.services.api.gateway.auth import Rctx, bearer_of
from acme.services.api.gateway.ratelimit import count, failures_counted
from acme.services.api.gateway.resolve import container_of


async def enrollment_token(authorization: Annotated[str | None, Header()] = None) -> str:
    """The enrollment token a host presents once, as its bearer. The hosts
    manager checks it; the route's budget is counted per address, as a
    sign-in's is, since no credential of the host's exists yet."""
    return bearer_of(authorization)


EnrollmentBearer = Annotated[str, Depends(enrollment_token)]


async def current_host(
    request: Request,
    rctx: Rctx,
    authorization: Annotated[str | None, Header()] = None,
) -> HostIdentity:
    """The host behind its own credential. The lookup counts its failures
    against the client address, and the credential spends its own budget,
    under its tenant, reads apart from writes."""
    hosts = container_of(request).managers.hosts
    credential = bearer_of(authorization)
    async with failures_counted(request):
        host = await hosts.authenticate(rctx, credential)
    route = "reads" if request.method in READ_METHODS else "writes"
    await count(request, route, host.org_id, f"cred:{host.credential_id}")
    return host


Host = Annotated[HostIdentity, Depends(current_host)]
