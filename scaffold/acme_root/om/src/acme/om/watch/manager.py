"""The watch swimlane: how a person sees and steers a running session
beyond the messages its inbox takes. A viewer reads the session's open
streams through a short-lived handle scoped to that session, a read and
never a push, while the realtime channel carries every change. A person
takes control: the agent stands down, its loop parked on a hand-over,
and the person's commands run as `exec` work on the host that holds the
workspace, each recorded as a run attributed to them. Giving it back
turns their summary into a message the agent reads on resume. A product's
claimant appends to its kind's stream for the item it holds, and a viewer
reads it by a handle to that item's streams, as a session's are read."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import RequestContext, TenantContext
from acme.om.hosts.types.host import ClaimantIdentity
from acme.om.relay.types.exec import ExecProgress
from acme.om.watch.types.control import HandCommand, HandRun
from acme.om.watch.types.live import (
    Appended,
    ItemPage,
    ItemRead,
    ItemSeen,
    LivePage,
    LiveRead,
    Seen,
)


class WatchManagerInterface(ABC):
    # The live read.

    @abstractmethod
    async def open_live(self, ctx: TenantContext, session_id: UUID) -> LiveRead:
        """A handle to the session's open streams, for a viewer who may read
        the session, that lasts the options' lifetime. A session the viewer
        cannot see is `NotFound`; a platform with no signing key is
        `Unavailable`."""
        ...

    @abstractmethod
    async def read_live(self, rctx: RequestContext, handle: str, seen: Sequence[Seen]) -> LivePage:
        """Platform-internal: the open streams of the one session the handle
        names, each from the part after the last `seen` names for it. The
        handle is the authority, as a presigned URL is, so this runs below
        any principal. A handle that does not verify, or has expired, is
        `LiveReadRefused`, and reads nothing."""
        ...

    # A product's streams, by the item a claimant holds.

    @abstractmethod
    async def append_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        kind: str,
        appended: Appended,
    ) -> None:
        """Platform-internal: the claimant appends to a stream of `kind` for
        the item it holds, in that item's group, under the kind's bounds. A
        kind its own kind does not write, the step's, and one nobody
        registered are `NotFound`, as is an item it does not hold: another
        claimant's, another tenant's, one handed back, or one its revoked
        identity held (`hosts.held_as`). Its own item under a lapsed lease,
        or a token the claim no longer carries, is `LeaseLost`. More than
        `MAX_APPEND_ENTRIES` entries, or `MAX_APPEND_BYTES` of them, is
        `ValidationFailed`, and lands nothing."""
        ...

    @abstractmethod
    async def open_item_live(self, ctx: TenantContext, item_id: UUID, kind: str) -> ItemRead:
        """A handle to the item's streams of a kind a claimant writes, for a
        viewer who may read the item's tenant, that lasts the options'
        lifetime. An item of another tenant, and a kind no claimant writes,
        are `NotFound`; a platform with no signing key is `Unavailable`."""
        ...

    @abstractmethod
    async def read_item_live(
        self, rctx: RequestContext, handle: str, seen: Sequence[ItemSeen]
    ) -> ItemPage:
        """Platform-internal: the open streams the handle names, each from
        the entry after the last `seen` names for it. The handle is the
        authority, as a session's is; one that does not verify as an item's,
        or has expired, is `LiveReadRefused`, and reads nothing."""
        ...

    # Take control, give back.

    @abstractmethod
    async def take_control(self, ctx: TenantContext, session_id: UUID) -> AgentSession:
        """A person, in person, who may instruct the session takes its
        environment: a new writer epoch fences the run that held the loop,
        which parks on a hand-over, and what that run's items still run on the
        host is stopped over its control stream and answered `interrupted`;
        the session, its workspace, and its evidence stay as they are.
        Parked on a hand-over already, it stays. Audited as that person."""
        ...

    @abstractmethod
    async def run_command(
        self, ctx: TenantContext, session_id: UUID, command: HandCommand
    ) -> HandRun:
        """A command the person runs while the agent stands down: audited as
        theirs before it is sent, then sent as unsafe `exec` work marked as
        a person's, which the host's owner may refuse, to the host that
        holds the workspace, in the workspace's pinned isolation, under the
        session's writer epoch, so it runs once and a run that
        takes the session after it fences it. The same key sent again meets
        the same run. `NotHandedOver` unless the session is parked on a
        hand-over; `NoWorkspaceHost` when no host holds its workspace."""
        ...

    @abstractmethod
    async def command(
        self, ctx: TenantContext, session_id: UUID, key: UUID, after_seq: int
    ) -> ExecProgress:
        """How the session's command under `key` stands, for a viewer of the
        session: its state, the parts of its output after `after_seq`, and
        how it ended once it has. `NotFound` for a key the session sent
        nothing under."""
        ...

    @abstractmethod
    async def give_back(
        self, ctx: TenantContext, session_id: UUID, summary: str, stop: bool = False
    ) -> AgentSession:
        """The person gives the environment back: their summary arrives as
        their message, an `environment_changed` step says a person acted
        there, and the hand-over is cleared, so the next run continues the
        loop under a new epoch that fences any command of theirs no host
        took yet. A command of theirs a host still runs refuses it,
        `CommandRunning`, unless `stop` asks it stopped first, answered
        `interrupted`. Audited as that person. `ValidationFailed` for a
        session not handed over."""
        ...
