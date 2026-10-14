"""Plans and the abstract unit.

The **unit** is a token unit weighted by cost: one unit is the reference cost
of `micros_per_unit` millionths, so a call's units are its reference cost
over that, and a unit plan can include usage across models and providers without
promising dollars or a token count. The scale is the platform's to publish,
by version; no tenant and no session sets it.

A **unit_plan** is versioned: a change is a new version, never an edit, and an
spend account names the version it is on. It says how many units each billing
period includes and what one unit drawn from a money bucket is charged."""

from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform

MAX_NAME = 200


class SpendUnitScale(Platform):
    """The published weight of the unit: the reference cost one unit stands
    for, in millionths of the reference currency."""

    version: str = Field(min_length=1, max_length=MAX_NAME)
    micros_per_unit: int = Field(ge=1)


class UnitPlanRef(Platform):
    id: str = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)


class UnitPlan(Platform):
    id: str = Field(min_length=1, max_length=MAX_NAME)
    version: int = Field(ge=1)
    included_units: int = Field(ge=0)  # each billing period
    unit_price_micros: int = Field(ge=1)  # one unit drawn from prepaid credits or a line of credit

    @property
    def ref(self) -> UnitPlanRef:
        return UnitPlanRef(id=self.id, version=self.version)


class UnitPlanCatalog(Platform):
    """Every version of every unit plan the platform publishes. A version is
    never changed in place; the latest of a unit plan is what a new spend account
    takes."""

    unit_plans: tuple[UnitPlan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_row_a_version(self) -> Self:
        keys = [(unit_plan.id, unit_plan.version) for unit_plan in self.unit_plans]
        if len(set(keys)) != len(keys):
            raise ValueError("a unit plan's version has one row in the catalog")
        return self

    def get(self, ref: UnitPlanRef) -> UnitPlan | None:
        for unit_plan in self.unit_plans:
            if unit_plan.id == ref.id and unit_plan.version == ref.version:
                return unit_plan
        return None

    def latest(self, unit_plan_id: str) -> UnitPlan | None:
        found = [unit_plan for unit_plan in self.unit_plans if unit_plan.id == unit_plan_id]
        return max(found, key=lambda unit_plan: unit_plan.version) if found else None


SPEND_UNITS = SpendUnitScale(version="2026-10-03", micros_per_unit=1_000)
"""One unit is a thousandth of the reference currency: a thousand tokens at
a list rate of one per million."""

UNIT_PLANS = UnitPlanCatalog(
    unit_plans=(
        UnitPlan(id="starter", version=1, included_units=20_000, unit_price_micros=1_200),
        UnitPlan(id="team", version=1, included_units=250_000, unit_price_micros=1_100),
        UnitPlan(id="enterprise", version=1, included_units=2_000_000, unit_price_micros=1_000),
    )
)
"""The unit plans the platform publishes. A product sets its own."""
