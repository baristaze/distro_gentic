"""Wire types of the cloud pool: its limits and a tenant's own maximum, as
an operator writes and reads them."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.cloud_pool.types.limits import MOST_VMS, WARM_BELOW_MOST, warm_below_most
from acme.services.api.types.common import RequestBody, View


class SetPoolLimitsRequest(RequestBody):
    """The pool's limits, written whole: the VMs kept warm and running, those
    kept warm and hibernated where the VMs hibernate, none unless named, the
    most VMs it holds at once, warm ones among them, and the most one tenant
    holds where no maximum of its own holds. The warm VMs, running and
    hibernated, stand below the most."""

    warm: int = Field(ge=0, le=MOST_VMS)
    hibernated: int = Field(default=0, ge=0, le=MOST_VMS)
    most: int = Field(ge=0, le=MOST_VMS)
    tenant_most: int = Field(ge=0, le=MOST_VMS)

    @model_validator(mode="after")
    def _warm_below_most(self) -> Self:
        if not warm_below_most(self.warm, self.hibernated, self.most):
            raise ValueError(WARM_BELOW_MOST)
        return self


class PoolLimitsView(View):
    """The pool's limits as the next claim reads them, at their version: 0
    while no operator wrote them, and the pool's options hold."""

    warm: int
    hibernated: int
    most: int
    tenant_most: int
    version: int
    updated_at: datetime


class SetTenantPoolLimitRequest(RequestBody):
    """A tenant's own maximum: the most VMs its sessions hold at once, in
    place of the pool's `tenant_most`."""

    most: int = Field(ge=0, le=MOST_VMS)


class TenantPoolLimitView(View):
    """A tenant's own maximum as the operator wrote it, at its version."""

    org_id: UUID
    most: int
    version: int
    updated_at: datetime
    updated_by: UUID
