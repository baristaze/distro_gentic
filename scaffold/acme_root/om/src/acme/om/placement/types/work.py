"""The payloads of the work a session produces outside the cloud's
runners: what each kind must name so its item goes to the lane where its
environment is. The work queue fixes them per kind (`WORK_PAYLOADS`); the
kinds that carry what a host or a daemon runs add their fields here."""

from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from acme.om.base import Platform


class ExecPayload(Platform):
    """A command or a file operation for the host that holds the session's
    workspace. Its item goes to that host's lane."""

    host_id: UUID


class WorkspaceOperation(StrEnum):
    PREPARE = "prepare"  # a host in the session's placement makes the workspace
    RELEASE = "release"  # the holding host lets it go
    PURGE = "purge"  # the holding host destroys it


class WorkspacePayload(Platform):
    """A workspace to prepare, release, or purge. Preparing goes to the lane
    of the session's placement, since any host of the pool may make it;
    releasing and purging go to the lane of the host that holds it, since
    a workspace lives where it was prepared."""

    operation: WorkspaceOperation
    pool_id: UUID | None = None
    host_id: UUID | None = None

    @model_validator(mode="after")
    def _names_where_it_runs(self) -> WorkspacePayload:
        preparing = self.operation is WorkspaceOperation.PREPARE
        if preparing != (self.pool_id is not None) or preparing == (self.host_id is not None):
            raise ValueError("a prepare names its pool alone, and a release or a purge its host")
        return self


class StationPayload(Platform):
    """Work on a station, for the daemon of the lab that serves it. Its item
    goes to that lab's lane."""

    lab_id: UUID
