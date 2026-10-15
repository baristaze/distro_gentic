"""An erasure the cloud pool owes: a session's disks, kept by the machines'
backend under its names, to be destroyed where the machines are reached.
The revocation of a session's key asks it in whichever process takes the
revocation; the sweep, which reaches the machines, carries it out."""

from uuid import UUID

from acme.om.base import Created, Identifiable


class PoolErasure(Identifiable, Created):
    """The platform's own record that the session's disks are to go: the
    tenant and the session whose names they are kept under. Never a disk's
    name, which the sweep reads off the machines' backend."""

    tenant_id: UUID
    agent_session_id: UUID
