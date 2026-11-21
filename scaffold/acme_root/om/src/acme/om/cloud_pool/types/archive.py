"""The pool's record of a session whose workspace files it archived: the
archives themselves live in the snapshots bucket, sealed under the
session's key, and the record says when the session last kept one or was
last seen active, so the sweep removes them once it has been idle past the
pool's `archive_kept` (ADR 2070)."""

from datetime import datetime
from uuid import UUID

from acme.om.base import Created, Identifiable


class PoolArchive(Identifiable, Created):
    """The platform's own row: the tenant and the session whose archives
    the pool keeps, and the latest moment it knows the session was active,
    `kept_at`, which moves; its id and when it came to be never do. Never
    a key or a byte of an archive."""

    tenant_id: UUID
    agent_session_id: UUID
    kept_at: datetime
