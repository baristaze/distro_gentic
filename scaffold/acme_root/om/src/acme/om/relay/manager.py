"""The relay swimlane: a tool call into a customer's wall as keyed `exec`
work. The runner's relay transport sends each operation of a call and waits
for it; the host that holds the session's workspace claims it under a
lease, reads it, streams its output, and pushes how it ended, which is
stored under the call's key; a host's control stream stops it at once."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.host import HostIdentity
from acme.om.relay.types.exec import (
    ExecCall,
    ExecControl,
    ExecDetail,
    ExecItem,
    ExecProgress,
    StopKind,
    WorkspaceBinding,
)
from acme.om.retention.crossing import Crossing
from acme.om.work.types.work_item import WorkItem


class RelayManagerInterface(ABC):
    # Where a session's workspace is.

    @abstractmethod
    async def bind_workspace(
        self, ctx: TenantContext, session_id: UUID, host_id: UUID, location: str
    ) -> WorkspaceBinding:
        """Platform-internal: the host that prepared the session's workspace
        holds it from now on, at `location` on the host, and every item of
        the session goes to that host. Refused (`ValidationFailed`) unless
        the session is pinned to the host's pool and the host is not
        revoked. Requires the write permission."""
        ...

    @abstractmethod
    async def binding_of(self, ctx: TenantContext, session_id: UUID) -> WorkspaceBinding | None:
        """The host that holds the session's workspace; None when none does."""
        ...

    # The runner's side: its relay transport, which runs below any context,
    # so each call mints the service context of the session's tenant.

    @abstractmethod
    async def send(
        self, rctx: RequestContext, org_id: UUID, call: ExecCall, occurrence: int
    ) -> ExecItem:
        """Platform-internal: the item of one operation of a call, made and
        put on the queue of the host that holds the session's workspace, or
        met when the same call sent it before (`rules.exec_id`). One met is
        answered as it stands, so a resumed run attaches to the first
        execution or reads its result; only a repeatable one whose last run
        was stopped or lost is put on the queue again. `StaleExec` for a
        command whose epoch is below the session's; `NoWorkspaceHost` when no
        host holds the workspace; `ContentNotKept` when the session keeps no
        content at rest."""
        ...

    @abstractmethod
    async def watch(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, after_seq: int
    ) -> ExecProgress:
        """Platform-internal: the item's state, the parts of its output after
        `after_seq`, opened, and how it ended once it has."""
        ...

    @abstractmethod
    async def stop(
        self, rctx: RequestContext, org_id: UUID, item_id: UUID, kind: StopKind, epoch: int | None
    ) -> ExecItem:
        """Platform-internal: ends the item at once. One no host holds yet
        never runs; one a host holds is stopped over its control stream.
        `StaleExec` from a run below the item's epoch, whose stop would end
        another run's command."""
        ...

    @abstractmethod
    async def outcome_of(
        self, rctx: RequestContext, org_id: UUID, session_id: UUID, key: UUID, epoch: int
    ) -> ExecItem | None:
        """Platform-internal: the command the call under `key` sent, for a
        run that recovers it, or None. It admits `epoch` first, as a command
        does: a command of a lost run that no host took yet never runs.
        `StaleExec` for an epoch below the session's."""
        ...

    # A host's side: the transitions its calls make from the request stage.

    @abstractmethod
    async def start(self, ctx: TenantContext, row: WorkItem) -> bool:
        """Platform-internal: a host's claim took the item's queue row.
        Whether the host is handed it: never a row the item no longer runs
        under, an unsafe item a claim took before, an item settled already,
        or a command whose epoch is below the session's; each such row is
        settled here, so it is never claimed again."""
        ...

    @abstractmethod
    async def detail(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> ExecDetail:
        """Platform-internal: what the host that holds the item runs, opened.
        `ItemNotHeld` for any other host, and once the item is settled."""
        ...

    @abstractmethod
    async def push_part(
        self,
        rctx: RequestContext,
        host: HostIdentity,
        item_id: UUID,
        seq: int,
        stream: str,
        crossing: Crossing,
        data: bytes,
    ) -> None:
        """Platform-internal: one part of the item's output, verified against
        the hash it crossed with before anything reads it, then kept sealed.
        A part sent again lands once. `CrossingRefused` for bytes that are
        not the ones declared; `ItemNotHeld` as `detail` says."""
        ...

    @abstractmethod
    async def push_result(
        self,
        rctx: RequestContext,
        host: HostIdentity,
        item_id: UUID,
        crossing: Crossing,
        data: bytes,
    ) -> ExecItem:
        """Platform-internal: how the item ended, verified against the hash
        it crossed with before anything reads it, stored under the call's
        key, and its queue row completed. The first settlement wins: a
        result for an item its lease, a stop, or the sweep settled already
        is `ItemNotHeld`, and lands nothing."""
        ...

    @abstractmethod
    async def extend(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> datetime:
        """Platform-internal: renews the host's lease on the item and answers
        when it ends now. `ItemNotHeld`, or `LeaseLost` when the queue row
        is no longer the host's."""
        ...

    @abstractmethod
    async def controls(
        self, rctx: RequestContext, host: HostIdentity, after: UUID | None
    ) -> list[ExecControl]:
        """Platform-internal: the host's control messages after `after`, or
        those of the last window when it names none: what a host that
        reconnects is told again."""
        ...

    # The sweep.

    @abstractmethod
    async def settle_expired(self, rctx: RequestContext) -> int:
        """Platform-internal: across tenants, each running item whose lease
        ended. An unsafe one completes `interrupted`, outcome unknown, and is
        never requeued; a repeatable one waits for its row to come back to
        its host's lane. Either way the host that held it is told its lease
        is revoked. Returns how many it settled."""
        ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID) -> None:
        """Platform-internal: what the relay keeps of a session the sweep
        purges: its items, their output, its controls, and its binding."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep's purge of a tenant deleted past its retention; any
        other tenant costs nothing."""
        ...
