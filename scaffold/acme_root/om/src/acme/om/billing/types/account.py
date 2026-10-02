"""A tenant's billing account: who pays, on which plan, in which time zone,
and from when its billing periods run. One per org, under the org's own id.

The funding mode says who pays the provider: the platform's key, billed to
the tenant through the buckets, or the tenant's own key. Prepaid and
postpaid are not modes: they differ only in which bucket pays (prepaid
credits, or a line of credit), never in the path a call takes."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self

from pydantic import Field, model_validator

from acme.om.base import Identifiable, Platform, Trackable
from acme.om.billing.types.plan import MAX_NAME, PlanRef

MAX_ZONES = 32
"""The zone changes an account keeps: enough to place every window still
open, since a change reaches back one window at most."""

PLATFORM_KEY = "platform"
"""The credential a call on the platform's own key runs on, as the outage
signal names it."""


class FundingMode(StrEnum):
    PLATFORM = "platform"  # the platform's key pays the provider; the buckets bill the tenant
    OWN_KEY = "own_key"  # the tenant's own provider key pays the provider


class ZoneChange(Platform):
    """The tenant's time zone from `at` on, an IANA name."""

    zone: str = Field(min_length=1, max_length=MAX_NAME)
    at: datetime


class Account(Identifiable, Trackable):
    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("version", "zones", "credit_line_micros")
    """The zones change by `set_time_zone`, the line of credit by an operator,
    and every change is a compare-and-set on the version."""

    funding: FundingMode
    key_ref: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    """The reference of the tenant's own key, for `own_key`; never its value."""
    plan_id: str = Field(min_length=1, max_length=MAX_NAME)
    plan_version: int = Field(ge=1)
    period_anchor: datetime
    """When the first billing period began: every month window and every
    period of a periodic bucket counts from it."""
    credit_line_micros: int = Field(default=0, ge=0)
    """An enterprise line of credit, each billing period; zero for none."""
    zones: tuple[ZoneChange, ...] = Field(min_length=1, max_length=MAX_ZONES)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _zones_in_order(self) -> Self:
        times = [change.at for change in self.zones]
        if times != sorted(times):
            raise ValueError("an account's zone changes are kept in the order they happened")
        return self

    @property
    def plan(self) -> PlanRef:
        return PlanRef(id=self.plan_id, version=self.plan_version)


class AccountRequest(Platform):
    """What an owner sets when the tenant's account opens."""

    funding: FundingMode
    key_ref: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    plan_id: str = Field(min_length=1, max_length=MAX_NAME)
    zone: str = Field(min_length=1, max_length=MAX_NAME)
