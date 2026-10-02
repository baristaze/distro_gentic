"""Hypotheses and findings: records too, each linked to the runs that
support or refute it. What one says is in the agent's step that stated
it, sealed with the session's history; the record holds its links."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable, Platform


class InferenceKind(StrEnum):
    HYPOTHESIS = "hypothesis"  # what may explain the behavior
    FINDING = "finding"  # what the runs show


class Stance(StrEnum):
    """What a finding says of the hypothesis it resolves."""

    SUPPORTED = "supported"
    REFUTED = "refuted"


class Inference(Identifiable, Created):
    """A hypothesis or a finding of one session. `step_id` is the agent's
    step that states it. A finding cites at least one run, and one that
    resolves a hypothesis says whether the runs support or refute it."""

    session_id: UUID
    step_id: UUID
    kind: InferenceKind
    resolves: UUID | None = None
    stance: Stance | None = None
    supports: tuple[UUID, ...] = Field(default=(), max_length=500)
    refutes: tuple[UUID, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def _linked(self) -> Self:
        if self.kind is InferenceKind.HYPOTHESIS and (self.resolves or self.stance):
            raise ValueError("a hypothesis resolves nothing")
        if (self.resolves is None) != (self.stance is None):
            raise ValueError("a finding that resolves a hypothesis says how, and only one")
        if self.kind is InferenceKind.FINDING and not (self.supports or self.refutes):
            raise ValueError("a finding cites the runs that show it")
        return self

    @property
    def runs(self) -> tuple[UUID, ...]:
        return (*self.supports, *self.refutes)


class InferencePage(Platform):
    items: tuple[Inference, ...]
    has_more: bool
