"""A session's workspace as the platform keeps it between loops. Its isolation
is pinned when the session is created and never changes: the level, the
limits, and the egress its project allowed then. The rest is what the cache
knows of the durable state it is rebuilt from: the session's branch, whether
the remote has held it, the last snapshot of its work, and what the next
loop must be told."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    ResourceLimits,
)
from acme.om.base import Identifiable, Trackable
from acme.om.workspaces.types.egress import EgressRule


class SessionWorkspace(Identifiable, Trackable):
    """One row a session; `id` is the session's."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "branch_seen",
        "snapshot_ref",
        "notice",
        "push_digest",
        "push_expires_at",
        "version",
    )

    project_id: UUID | None = None
    level: IsolationMode
    limits: ResourceLimits = ResourceLimits()
    egress: EgressMode
    rules: tuple[EgressRule, ...] = ()
    # Where its egress came from, as a person reads it: its project's
    # allowlist at its version, with the reason open egress was chosen, or
    # its kind's own.
    egress_source: str = Field(min_length=1, max_length=1000)
    branch: str = Field(min_length=1, max_length=200)
    # The remote held the session's branch at a release: gone after that,
    # it vanished.
    branch_seen: bool = False
    snapshot_ref: str | None = Field(default=None, max_length=255)
    # What the next loop is told before its first call; cleared once told.
    notice: str | None = Field(default=None, max_length=2000)
    # The digest of the one push token the loop holds, and when it expires;
    # a prepare or a release clears both, so no token outlives its loop.
    push_digest: str | None = Field(default=None, max_length=64)
    push_expires_at: datetime | None = None
    version: int = Field(default=1, ge=1)

    def spec(self) -> IsolationSpec:
        """The pinned isolation, as a provider prepares it. An allowlist's
        destinations name its hosts; their methods are the egress proxy's to
        hold, from the rules here."""
        hosts = tuple(dict.fromkeys(rule.destination for rule in self.rules))
        egress = EgressPolicy(mode=self.egress, hosts=hosts)
        return IsolationSpec(mode=self.level, egress=egress, limits=self.limits)
