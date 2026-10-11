"""A host pool: one or more hosts inside a tenant's wall that share labels,
in a region. A session placed on a pool runs its work on its hosts alone."""

from typing import Annotated
from uuid import UUID

from pydantic import StringConstraints

from acme.om.base import Identifiable, Trackable

PoolName = Annotated[str, StringConstraints(min_length=1, max_length=64)]

Region = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
"""A region's name, short and plain: `eu-west`, `office-istanbul`."""

Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,62}$")]


class HostPool(Identifiable, Trackable):
    """One row a pool. Its hosts enroll into it with a token issued for it,
    and the pool is the only place their claims come from. A pool that names
    a session is the platform's, not the tenant's: the pool of one that the
    cloud pool's machine of that session enrolls into, with the key the
    platform handed the machine, never a token. No session is placed on it,
    and no person issues a token for it."""

    name: PoolName
    region: Region
    labels: tuple[Label, ...] = ()
    session_id: UUID | None = None
