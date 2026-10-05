"""A validation: one pass of a policy's checks on a fresh executor, from a
commit, with the checks, fixtures, and runner from the protected source.
What a session delivered, as the work product reports it, and what a
validation is asked to run."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable, Platform
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.policy import PATTERN
from acme.om.evidence.types.provenance import SHA256
from acme.om.evidence.types.rate import RateRule
from acme.om.evidence.types.record import PROJECT, VERSION, RunPurpose


class Delivery(Platform):
    """What a session's work product holds now, as the system that keeps it
    reports it, never as the agent describes it: the name its project goes
    by there, the version the work started from, the committed head,
    whether the tree holds uncommitted changes, and every path changed from
    the base, committed or not. No policy is read by that name: a session
    is judged by its own project's."""

    project: str = Field(pattern=PROJECT)
    base: str = Field(pattern=VERSION)
    head: str = Field(pattern=VERSION)
    dirty: bool = False
    changed: tuple[str, ...] = ()

    @property
    def changes_work_product(self) -> bool:
        return self.head != self.base or self.dirty or bool(self.changed)


class ExecutionRequest(Platform):
    """What a fresh executor is asked to run: the checks, at `version`, with
    their checks, fixtures, and runner taken from `source`, the protected
    source, and under an environment the executor sets. `protected` holds
    the patterns of those paths: every path one matches comes from
    `source`, whatever the tree at `version` holds there. `source` is a
    commit of the repository `project` binds, or of the one
    `source_project` binds when the request names it: a hidden suite's
    source of its own. `untouched` holds the patterns of the paths no
    change may touch: every path one matches, and no `protected` one does,
    comes from the commit `base` of the repository `project` binds. Every
    path either matches is read-only to the checks while they run, and a
    trial that changes one has no verdict, so no copy the head makes of
    what scores a run scores it, in the tree or while it runs. Nothing of the
    agent's workspace or environment is in it. Each check runs at most its
    count of trials; one with a rate stops where `rates.stops_at` says its
    rule stops, at the confidence given here, and nowhere else."""

    session_id: UUID
    project: str = Field(pattern=PROJECT)
    purpose: RunPurpose
    version: str = Field(pattern=VERSION)
    source: str = Field(pattern=VERSION)
    checks: tuple[CheckDeclaration, ...] = Field(min_length=1)
    trials: tuple[int, ...] = Field(min_length=1)
    rates: tuple[RateRule | None, ...] = ()
    protected: tuple[PATTERN, ...] = ()
    source_project: str | None = Field(default=None, pattern=PROJECT)
    base: str | None = Field(default=None, pattern=VERSION)
    untouched: tuple[PATTERN, ...] = ()

    @model_validator(mode="after")
    def _a_count_a_check(self) -> Self:
        if bool(self.untouched) != (self.base is not None):
            raise ValueError("a request names the base its untouched paths come from, or neither")
        if len(self.trials) != len(self.checks) or min(self.trials) < 1:
            raise ValueError("each check is asked for its own count of trials, at least one")
        if self.rates and len(self.rates) != len(self.checks):
            raise ValueError("a request names each check's rate, or none of them")
        if self.purpose is RunPurpose.WORK:
            raise ValueError("the executor runs a baseline or a validation, never the agent's work")
        return self


class Prepared(Platform):
    """What a fresh executor made a run's instance as: the host that made
    it, its isolation, and the image it runs. A record of the executor's
    names these, never what the runner's start line says, since the
    delivered code writes that line."""

    host: str = Field(min_length=1, max_length=200)
    isolation: str = Field(min_length=1, max_length=100)
    image: str = Field(pattern=VERSION)


class ExecutorReport(Platform):
    """What a fresh executor answers: who it is, what it made the run's
    instance as, the results stream it wrote, and its hash of that stream,
    taken where it was written."""

    executor: str = Field(min_length=1, max_length=200)
    prepared: Prepared
    results: bytes
    sha256: str = Field(pattern=SHA256)


class Validation(Identifiable, Created):
    """One pass of the executor's, kept with the runs it wrote: what it ran
    at (`version`) and from (`source`), who ran it, and the executor's hash
    of the results it wrote. The gate accepts its runs only when each names
    this executor and the hash still holds."""

    session_id: UUID
    project: str = Field(pattern=PROJECT)
    purpose: RunPurpose
    version: str = Field(pattern=VERSION)
    source: str = Field(pattern=VERSION)
    executor: str = Field(min_length=1, max_length=200)
    results_sha256: str = Field(pattern=SHA256)
    records: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def _the_executors(self) -> Self:
        if self.purpose is RunPurpose.WORK:
            raise ValueError("a validation is a baseline's or a validation's, never the agent's")
        return self
