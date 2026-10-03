"""Storage of the relay: each `exec` item with how it ended, the parts of
its output, the control messages for the host that holds it, and the host
that holds each session's workspace. Every operation takes org_id first,
except the sweep's read of expired leases, which reaches across tenants. A
write that announces a change lands its outbox rows in the same commit."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.relay.types.exec import ExecControl, ExecItem, ExecPart, WorkspaceBinding


class RelayStorageInterface(ABC):
    @abstractmethod
    async def create_item(self, org_id: UUID, item: ExecItem) -> bool:
        """The create; False, with nothing landed, when the id is written."""
        ...

    @abstractmethod
    async def read_item(self, org_id: UUID, item_id: UUID) -> ExecItem | None: ...

    @abstractmethod
    async def read_items_by_key(
        self, org_id: UUID, session_id: UUID, key: UUID, limit: int
    ) -> list[ExecItem]:
        """The items of one call, oldest first, at most `limit`."""
        ...

    @abstractmethod
    async def read_running(self, org_id: UUID, session_id: UUID, limit: int) -> list[ExecItem]:
        """The session's items a host runs now, oldest first, at most
        `limit`."""
        ...

    @abstractmethod
    async def write_item(
        self, org_id: UUID, item: ExecItem, expected_version: int
    ) -> ExecItem | None:
        """A compare-and-set: `item` lands over the row stored at
        `expected_version`. None, landing nothing, when the row is at
        another."""
        ...

    @abstractmethod
    async def read_expired(self, now: datetime, limit: int) -> list[tuple[UUID, ExecItem]]:
        """Cross-tenant, for the sweep: running items whose lease ended
        before `now`, each with its tenant, at most `limit`."""
        ...

    @abstractmethod
    async def add_part(self, org_id: UUID, part: ExecPart) -> bool:
        """The create; False, with nothing landed, when the row's part at
        that place is written."""
        ...

    @abstractmethod
    async def read_parts(
        self, org_id: UUID, row_id: UUID, after_seq: int, limit: int
    ) -> list[ExecPart]:
        """The parts of a row's output after `after_seq`, in order."""
        ...

    @abstractmethod
    async def add_control(
        self, org_id: UUID, control: ExecControl, outbox_rows: tuple[OutboxRow, ...]
    ) -> None: ...

    @abstractmethod
    async def read_controls(
        self, org_id: UUID, host_id: UUID, after: UUID | None, since: datetime, limit: int
    ) -> list[ExecControl]:
        """The host's control messages made at `since` or later, after the
        one `after` names when it names one, in id order."""
        ...

    @abstractmethod
    async def write_binding(
        self,
        org_id: UUID,
        binding: WorkspaceBinding,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """A compare-and-set: 0 creates the session's row, any other version
        lands the binding over the one stored at it. `PreconditionFailed`,
        landing nothing, when the stored version is another."""
        ...

    @abstractmethod
    async def read_binding(self, org_id: UUID, session_id: UUID) -> WorkspaceBinding | None: ...

    @abstractmethod
    async def read_bindings(
        self, after: UUID | None, limit: int
    ) -> list[tuple[UUID, WorkspaceBinding]]:
        """Cross-tenant, for the sweep: the bindings in id order after the one
        `after` names when it names one, each with its tenant, at most
        `limit`."""
        ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        """At most `limit` rows of each table that hold the session's: its
        items, their parts and controls, and its binding; returns how many
        went."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each table of a deleted tenant past its
        retention; returns how many went."""
        ...
