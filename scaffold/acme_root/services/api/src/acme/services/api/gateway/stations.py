"""The gateway's transition for a lab's station daemon, a client of the
gateway that is no person. Its every call carries its own credential,
whose prefix no other transition accepts. Its identity comes from that
credential alone, so nothing a daemon sends names its tenant, its lab, or
a lane."""

from typing import Annotated

from fastapi import Depends, Header, Request

from acme.om.stations.types.daemon import DaemonIdentity
from acme.services.api.gateway.admission import READ_METHODS
from acme.services.api.gateway.auth import Rctx, bearer_of
from acme.services.api.gateway.ratelimit import count, failures_counted
from acme.services.api.gateway.resolve import container_of


async def current_daemon(
    request: Request,
    rctx: Rctx,
    authorization: Annotated[str | None, Header()] = None,
) -> DaemonIdentity:
    """The daemon behind its own credential. The lookup counts its failures
    against the client address, and the credential spends its own budget,
    under its tenant, reads apart from writes."""
    stations = container_of(request).managers.stations
    credential = bearer_of(authorization)
    async with failures_counted(request):
        daemon = await stations.authenticate(rctx, credential)
    route = "reads" if request.method in READ_METHODS else "writes"
    await count(request, route, daemon.org_id, f"cred:{daemon.credential_id}")
    return daemon


Daemon = Annotated[DaemonIdentity, Depends(current_daemon)]
