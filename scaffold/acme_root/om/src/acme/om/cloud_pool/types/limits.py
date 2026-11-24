"""The cloud pool's limits, which its operators write and every claim and
refill reads: how many VMs stand warm, running or hibernated, how many
the pool holds at once, and how many one tenant holds at once. A VM held
counts against both maxima from its start, or its claim, until it is let
go, whether it runs, starts, sleeps, or stands stopped for its session."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Identifiable, Trackable

MOST_VMS = 100_000
"""Far above any pool a deployment runs, and well inside the column's range."""

WARM_BELOW_MOST = "the warm VMs, running and hibernated, stand below the most the pool holds"


def warm_below_most(warm: int, hibernated: int, most: int) -> bool:
    """Whether the warm VMs, running and hibernated, stand below the most
    the pool holds, or none stands."""
    return not (warm or hibernated) or warm + hibernated < most


class Full(StrEnum):
    """The maximum a claim found reached, so it started no VM."""

    POOL = "pool"  # the VMs the pool holds at once
    TENANT = "tenant"  # the VMs the claim's tenant holds at once


class PoolLimits(Identifiable, Trackable):
    """The pool's own limits, one row the platform's operators write, a new
    version each time; with none, the pool's options hold. `warm` VMs stand
    running ahead of demand, and `hibernated` more sleep, where the VMs
    hibernate; `most` VMs the pool holds at once, warm ones among them,
    and `tenant_most` VMs one tenant holds at once where no operator set it
    a maximum of its own. Warm VMs, running and hibernated, stand below
    `most`, and at the maximum a claim that takes no warm VM takes the
    place of an idle one, so a warm VM that stands never keeps a session
    waiting."""

    warm: int = Field(ge=0, le=MOST_VMS)
    hibernated: int = Field(default=0, ge=0, le=MOST_VMS)
    most: int = Field(ge=0, le=MOST_VMS)
    tenant_most: int = Field(ge=0, le=MOST_VMS)
    version: int = 1

    @model_validator(mode="after")
    def _warm_below_most(self) -> Self:
        if not warm_below_most(self.warm, self.hibernated, self.most):
            raise ValueError(WARM_BELOW_MOST)
        return self


class TenantPoolLimit(Identifiable, Trackable):
    """A tenant's own maximum, one row the platform's operators write in
    place of the pool's `tenant_most`: the VMs its sessions hold at once."""

    most: int = Field(ge=0, le=MOST_VMS)
    version: int = 1
