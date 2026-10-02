"""The platform's agents swimlane: the validation session, a check run on a
station with no agent at all. Its kinds and their tools are profiles over
the engine's loop (`kinds.py`, `tools.py`), which a root wires; this
manager holds what has a record of its own.

A validation session is station work on the same queue an agent's takes,
on its lab's lane, and its run is the same execution record. Nothing in
its path asks for a loop or calls a model."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.platform_agents.types.validation import ValidationSession, ValidationStart


class PlatformAgentsManagerInterface(ABC):
    @abstractmethod
    async def start_validation(
        self, ctx: TenantContext, start: ValidationStart
    ) -> ValidationSession:
        """A validation session, and its station work on its lab's lane, in
        one write: the lab's daemon claims it through the gateway and runs
        the check. Requires the write permission. A start asked again under
        the same id answers the session as stored."""
        ...

    @abstractmethod
    async def get_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSession:
        """A validation session of the tenant; `NotFound` when another tenant
        holds it, or none does."""
        ...

    @abstractmethod
    async def finish_validation(
        self, ctx: TenantContext, session_id: UUID, run_id: UUID
    ) -> ValidationSession:
        """Platform-internal: the daemon's run is recorded as `run_id`, the
        execution record every run is, and the session is finished. Asked
        again with the same run, it answers the session as stored; with
        another, `PreconditionFailed`, since a session runs its check once."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its validation
        sessions, a batch at most a call. Any other tenant returns 0 and
        reads nothing."""
        ...
