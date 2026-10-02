"""A project's validation policy: which checks must pass, at what grade,
for which kinds of change, for a success to count; and the paths the
agent may not change, by pattern."""

from enum import StrEnum
from typing import Annotated, ClassVar, Self

from pydantic import Field, model_validator

from acme.om.base import Identifiable, Platform, Trackable
from acme.om.evidence.types.contract import SCHEMAS, CheckDeclaration
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.rate import RateRule
from acme.om.evidence.types.record import NAME, PROJECT

PATTERN = Annotated[str, Field(min_length=1, max_length=300, pattern=r"^[^\s\\]+$")]
"""A path pattern, from the work product's root: `*` within one part of a
path, `**` across parts, as `PurePosixPath.full_match` reads it."""


class Grade(StrEnum):
    """The weakest provenance a passing run of a check may have. A double is
    no grade: its run is never validation."""

    REAL = "real"  # only the system itself
    TWIN = "twin"  # the real system or its twin

    @property
    def floor(self) -> Provenance:
        return Provenance(self.value)


class Requirement(Platform):
    """A check that must pass for a kind of change: a change that touches a
    path one of `paths` matches. `rate`, when set, asks for repeated trials
    whose failure rate is bounded under it."""

    check: str = Field(pattern=NAME)
    grade: Grade = Grade.TWIN
    paths: tuple[PATTERN, ...] = Field(default=("**",), min_length=1)
    rate: RateRule | None = None


class ValidationPolicy(Identifiable, Trackable):
    """One project's policy, written by a person, never by an agent. Its
    checks are declared here; its requirements name them; `protected`
    holds the patterns of every path the agent may not change: the checks,
    their fixtures, and every path that changes how tests are found or how
    the runtime starts. The policy itself is this record, which no tool
    reaches."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ("version",)

    project: str = Field(pattern=PROJECT)
    checks: tuple[CheckDeclaration, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    protected: tuple[PATTERN, ...] = ()
    # Every write after the create is a compare-and-set on it.
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        names = [check.name for check in self.checks]
        if len(set(names)) != len(names):
            raise ValueError("each check is declared once")
        unknown = sorted({req.check for req in self.requirements} - set(names))
        if unknown:
            raise ValueError(f"requirements name checks the policy does not declare: {unknown}")
        unread = sorted(check.name for check in self.checks if check.schema_version not in SCHEMAS)
        if unread:
            raise ValueError(f"checks write a results schema no collector reads: {unread}")
        return self

    def declared(self, name: str) -> CheckDeclaration:
        return next(check for check in self.checks if check.name == name)
