"""The stations service: what the wire can do with a tenant's labs, pools,
and stations, its daemons, the line, leases, and jobs, and what a lab
daemon's own calls do, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.stations.types.daemon import DaemonIdentity
from acme.services.api.types.stations import (
    CreateLabRequest,
    CreateStationPoolRequest,
    CreateStationRequest,
    IssuedDaemonCredentialView,
    JobReportRequest,
    JoinLineRequest,
    LabView,
    LeaseTimeView,
    LeaseView,
    LeftLinesView,
    LinePlaceView,
    ReorderRequest,
    RevokedDaemonView,
    StationClaimRequest,
    StationClaimView,
    StationJobView,
    StationPoolView,
    StationView,
    SubmitJobRequest,
)


class StationsServiceInterface(ABC):
    # A tenant's calls.

    @abstractmethod
    async def create_lab(self, ctx: TenantContext, body: CreateLabRequest, lab_id: UUID) -> LabView:
        """A lab under `lab_id`, the id the idempotency record minted."""
        ...

    @abstractmethod
    async def create_pool(
        self, ctx: TenantContext, body: CreateStationPoolRequest, pool_id: UUID
    ) -> StationPoolView: ...

    @abstractmethod
    async def add_station(
        self, ctx: TenantContext, body: CreateStationRequest, station_id: UUID
    ) -> StationView: ...

    @abstractmethod
    async def get_stations(self, ctx: TenantContext, pool_id: UUID) -> list[StationView]: ...

    @abstractmethod
    async def issue_daemon_credential(
        self, ctx: TenantContext, lab_id: UUID
    ) -> IssuedDaemonCredentialView: ...

    @abstractmethod
    async def revoke_daemon(self, ctx: TenantContext, lab_id: UUID) -> RevokedDaemonView: ...

    @abstractmethod
    async def join(
        self, ctx: TenantContext, pool_id: UUID, body: JoinLineRequest, entry_id: UUID
    ) -> LinePlaceView: ...

    @abstractmethod
    async def get_line(self, ctx: TenantContext, pool_id: UUID) -> list[LinePlaceView]: ...

    @abstractmethod
    async def reorder(
        self, ctx: TenantContext, entry_id: UUID, body: ReorderRequest
    ) -> LinePlaceView: ...

    @abstractmethod
    async def leave(self, ctx: TenantContext, session_id: UUID) -> LeftLinesView: ...

    @abstractmethod
    async def release_lease(self, ctx: TenantContext, lease_id: UUID) -> LeaseView: ...

    @abstractmethod
    async def revoke_lease(self, ctx: TenantContext, lease_id: UUID) -> LeaseView: ...

    @abstractmethod
    async def submit_job(
        self, ctx: TenantContext, lease_id: UUID, body: SubmitJobRequest, job_id: UUID
    ) -> StationJobView: ...

    # A daemon's calls.

    @abstractmethod
    async def rotate(
        self, rctx: RequestContext, daemon: DaemonIdentity
    ) -> IssuedDaemonCredentialView: ...

    @abstractmethod
    async def claim(
        self, rctx: RequestContext, daemon: DaemonIdentity, body: StationClaimRequest
    ) -> StationClaimView: ...

    @abstractmethod
    async def renew(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID
    ) -> LeaseTimeView: ...

    @abstractmethod
    async def report(
        self, rctx: RequestContext, daemon: DaemonIdentity, job_id: UUID, body: JobReportRequest
    ) -> StationJobView: ...
