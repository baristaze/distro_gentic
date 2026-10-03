"""An execution record: one run of one check, tied to the version and the
environment it ran in. It is written once and never changed."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, FrozenMapping, Identifiable, Platform
from acme.om.evidence.types.provenance import ArtifactRef, Dependency, Provenance, weakest

NAME = r"^[a-z][a-z0-9_.-]{0,99}$"
"""A check's name, and a kind's."""
PROJECT = r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,199}$"
"""A project's key: the name its tenant gives the work product, such as
its repository's."""
VERSION = r"^\S{1,200}$"
"""A version: a commit, a tag, an image digest. No whitespace."""


class RunPurpose(StrEnum):
    """Why a run ran. Only the executor writes a `baseline` or a
    `validation` run; the agent's own runs are `work`."""

    WORK = "work"  # the agent ran it, in its workspace
    BASELINE = "baseline"  # the executor ran it at the base version, before any change
    VALIDATION = "validation"  # the executor ran it at the delivered head


class RunOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"  # it could not run to a verdict: a broken fixture, a crash
    ABORTED = "aborted"  # an abort ended it; a declared rule classifies it


class Environment(Platform):
    """What a run ran under: the image's digest and the toolchain's
    versions, by name."""

    image: str = Field(pattern=VERSION)
    toolchain: FrozenMapping = Field(default_factory=dict, validate_default=True)


class CaseTally(Platform):
    """The cases a run streamed, counted by outcome."""

    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class ExecutionRecord(Identifiable, Created):
    """One run: the version it ran against and whether the tree held
    uncommitted changes, the environment, the host and its isolation, who
    ran it and wrote its results (`executor`), the check and its version,
    its parameters, metrics, timing, and outcome, its artifacts, and every
    dependency it relied on with its provenance. `step_id` is the tool call
    of the agent's that ran it, for a `work` run; `validation_id` the
    validation that ran it, for the executor's."""

    session_id: UUID
    project: str = Field(pattern=PROJECT)
    purpose: RunPurpose
    step_id: UUID | None = None
    validation_id: UUID | None = None
    version: str = Field(pattern=VERSION)
    dirty: bool
    environment: Environment
    host: str = Field(min_length=1, max_length=200)
    isolation: str = Field(min_length=1, max_length=100)
    executor: str = Field(min_length=1, max_length=200)
    check: str = Field(pattern=NAME)
    check_version: str = Field(pattern=VERSION)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)
    metrics: FrozenMapping = Field(default_factory=dict, validate_default=True)
    started_at: datetime
    finished_at: datetime
    outcome: RunOutcome
    cases: CaseTally = Field(default_factory=CaseTally)
    artifacts: tuple[ArtifactRef, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    abort: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("a run finishes after it starts")
        if (self.outcome is RunOutcome.ABORTED) != (self.abort is not None):
            raise ValueError("an aborted run names its abort, and only an aborted one")
        if self.outcome is RunOutcome.PASSED and self.cases.failed:
            raise ValueError("a run with a failed case did not pass")
        executor_run = self.purpose is not RunPurpose.WORK
        if executor_run != (self.validation_id is not None):
            raise ValueError("a baseline or validation run names its validation, and only one")
        if executor_run and self.dirty:
            raise ValueError("the executor runs from a commit, never a dirty tree")
        return self

    @property
    def passing(self) -> bool:
        """Whether the run passed: its outcome says so and at least one of its
        cases passed. A run whose cases were all skipped, or that reported
        none, showed nothing."""
        return self.outcome is RunOutcome.PASSED and self.cases.passed > 0

    @property
    def provenance(self) -> Provenance:
        """What served the run, as it is reported: its weakest dependency's
        provenance. A run a twin served is a twin's run, never real."""
        return weakest(*(dependency.provenance for dependency in self.dependencies))


class ExecutionRecordPage(Platform):
    items: tuple[ExecutionRecord, ...]
    has_more: bool
