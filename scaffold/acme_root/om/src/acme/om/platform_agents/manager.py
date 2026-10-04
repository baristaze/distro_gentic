"""The platform's agents swimlane: the validation session, a delivery's
check run with no agent at all. Its kinds and their tools are profiles over
the engine's loop (`kinds.py`, `tools.py`), which a root wires; this
manager holds what has a record of its own.

A validation session is platform work on the same queue an agent's takes,
run on a fresh executor through the evidence namespace, and its run is the
same execution record. Nothing in its path asks for a loop or calls a
model."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.platform_agents.types.validation import ValidationSession, ValidationStart


class PlatformAgentsManagerInterface(ABC):
    @abstractmethod
    async def start_validation(
        self, ctx: TenantContext, start: ValidationStart
    ) -> ValidationSession:
        """A validation session, and its work on the queue, in one write:
        the platform's worker claims it and runs the check
        (`run_validation`). Requires the write permission. Refused before
        anything is written when the tenant holds no validation policy for
        its project (`NotFound`, as another tenant's project is), or the
        policy declares no such check (`ValidationFailed`). A start asked
        again under the same id, of a check still declared, answers the
        session as stored."""
        ...

    @abstractmethod
    async def get_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSession:
        """A validation session of the tenant; `NotFound` when another tenant
        holds it, or none does."""
        ...

    @abstractmethod
    async def run_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSession:
        """Platform-internal, the work its start asked for: the session's
        check run once on a fresh executor, through the evidence namespace,
        at its head with the checks, fixtures, and runner from its base, and
        the session finished with the execution record that run wrote. A
        finished session runs nothing. Asked again after the run was kept,
        it runs nothing more and finishes with that run."""
        ...

    @abstractmethod
    async def finish_validation(
        self, ctx: TenantContext, session_id: UUID, run_id: UUID
    ) -> ValidationSession:
        """Platform-internal: the session's run is recorded as `run_id`, the
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
