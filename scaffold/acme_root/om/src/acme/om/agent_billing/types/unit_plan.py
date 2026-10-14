"""Plans and the abstract unit.

The **unit** is a token unit weighted by cost: one unit is the reference cost
of `micros_per_unit` millionths, so a call's units are its reference cost
over that, and a plan can include usage across models and providers without
promising dollars or a token count. The scale is the platform's to publish,
by version; no tenant and no session sets it.

A **plan** is versioned: a change is a new version, never an edit, and an
account names the version it is on. It says how many units each billing
period includes and what one unit drawn from a money bucket is charged."""

from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform

MAX_NAME = 200


class UnitScale(Platform):
    """The published weight of the unit: the reference cost one unit stands
    for, in millionths of the reference currency."""

    version: str = Field(min_length=1, max_length=MAX_NAME)
    micros_per_unit: int = Field(ge=1)


class PlanRef(Platform):
    id: str = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)


class Plan(Platform):
    id: str = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)
    included_units: int = Field(ge=0)  # each billing period
    unit_price_micros: int = Field(ge=1)  # one unit drawn from prepaid credits or a line of credit

    @property
    def ref(self) -> PlanRef:
        return PlanRef(id=self.id, version=self.version)


class PlanCatalog(Platform):
    """Every version of every plan the platform publishes. A version is
    never changed in place; the latest of a plan is what a new account
    takes."""

    plans: tuple[Plan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_row_a_version(self) -> Self:
        keys = [(plan.id, plan.version) for plan in self.plans]
        if len(set(keys)) != len(keys):
            raise ValueError("a plan's version has one row in the catalog")
        return self

    def get(self, ref: PlanRef) -> Plan | None:
        for plan in self.plans:
            if plan.id == ref.id and plan.version == ref.version:
                return plan
        return None

    def latest(self, plan_id: str) -> Plan | None:
        found = [plan for plan in self.plans if plan.id == plan_id]
        return max(found, key=lambda plan: plan.version) if found else None


UNITS = UnitScale(version="2026-10-03", micros_per_unit=1_000)
"""One unit is a thousandth of the reference currency: a thousand tokens at
a list rate of one per million."""

PLANS = PlanCatalog(
    plans=(
        Plan(id="starter", version=1, included_units=20_000, unit_price_micros=1_200),
        Plan(id="team", version=1, included_units=250_000, unit_price_micros=1_100),
        Plan(id="enterprise", version=1, included_units=2_000_000, unit_price_micros=1_000),
    )
)
"""The plans the platform publishes. A product sets its own."""
