"""The model matrix: which fills serve which question, by version.

A question names an environment, a model role, an agent kind, a plan tier,
and a workload class, and, for a role its kind asks a size of, the model
size. A row names any of the six, and leaves the rest open; the row that
matches every question names none. The most specific row that matches
wins: for a question that asks a size, a row that names the kind before a
row that names the size, and that before the rest. A version publishes
only with the row that matches everything, so every question has an
answer.

A version is written once, pending, and then published as it is: an edit
is a new version. The current matrix is the latest version published."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from acme.om.attribution.types.principal import MAX_KIND
from acme.om.base import Identifiable, Platform
from acme.om.models.types.fill import Fill, ModelRole, ModelSize
from acme.om.placement.types.share import PlanTier

NAME = r"^[a-z][a-z0-9-]{0,31}$"

Environment = Annotated[str, StringConstraints(pattern=NAME)]
"""Where the platform runs, as its root names it: `local`, `staging`,
`production`."""

WorkloadClass = Annotated[str, StringConstraints(pattern=NAME)]
"""A class of work a product names for its sessions. With none named, every
session's is `standard`."""

AgentKindName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_KIND)]

MAX_ROWS = 500
"""The rows one version holds at most."""

MAX_FILLS = 8
"""The fills one row holds at most: its fill and its fallbacks."""

MAX_ROLES = 64
"""The model roles one version serves at most."""

KEYS = ("environment", "size", "role", "kind", "plan_tier", "workload")
"""The six keys of a question, in the spec's order. Of two rows that name
as many keys, the one that names the earlier key is the more specific."""


class MatrixQuery(Platform):
    """One question: which fills serve this model role, for this agent kind
    on this plan tier, in this workload class and environment. `size` is the
    model size the kind asks of the role, and None when it asks none, which
    no row that names a size answers."""

    environment: Environment
    size: ModelSize | None = None
    role: ModelRole
    kind: AgentKindName
    plan_tier: PlanTier
    workload: WorkloadClass


class MatrixKey(Platform):
    """What a row answers: each key it names must equal the question's, and
    a key left None matches every value."""

    environment: Environment | None = None
    size: ModelSize | None = None
    role: ModelRole | None = None
    kind: AgentKindName | None = None
    plan_tier: PlanTier | None = None
    workload: WorkloadClass | None = None

    def matches(self, query: MatrixQuery) -> bool:
        return all(
            getattr(self, key) is None or getattr(self, key) == getattr(query, key) for key in KEYS
        )

    def specificity(self, query: MatrixQuery) -> tuple[int, int, tuple[bool, ...]]:
        """How specific the row is for `query`, a question it matches. For
        a question that asks a size, a row that names the kind comes first,
        whatever else it or a size's row names, so an operator's row for a
        kind is never passed over for a size's; then a row that names the
        size, as the engine answers an ask by its size; then the rest.
        Within each, and for a question that asks no size, which no row that
        names a size matches, the row that names more keys, then the one
        that names the earlier key, in the spec's order. Two rows that
        compare equal name the same keys, so two rows that match one
        question with it are the same row."""
        named = tuple(getattr(self, key) is not None for key in KEYS)
        first = 0
        if query.size is not None:
            first = 2 if self.kind is not None else 1 if self.size is not None else 0
        return first, sum(named), named

    @property
    def everything(self) -> bool:
        """Whether it matches every question."""
        return all(getattr(self, key) is None for key in KEYS)


class MatrixRow(Platform):
    """A row: what it answers, and its fills in order, the first the fill
    and the rest the fallbacks a failing provider falls to."""

    key: MatrixKey = MatrixKey()
    fills: tuple[Fill, ...] = Field(min_length=1, max_length=MAX_FILLS)

    @model_validator(mode="after")
    def _a_fill_once(self) -> Self:
        if len(set(self.fills)) != len(self.fills):
            raise ValueError("a row names a fill once")
        return self


class MatrixStatus(StrEnum):
    PENDING = "pending"  # written, and checked only when it is published
    PUBLISHED = "published"  # the matrix from its publication until the next


class MatrixVersion(Identifiable):
    """One version of the matrix: the model roles it serves, and its rows.
    Its rows never change; publishing it changes its status alone."""

    number: int = Field(ge=1)
    roles: tuple[ModelRole, ...] = Field(min_length=1, max_length=MAX_ROLES)
    rows: tuple[MatrixRow, ...] = Field(min_length=1, max_length=MAX_ROWS)
    status: MatrixStatus = MatrixStatus.PENDING
    created_at: datetime
    created_by: UUID  # the operator's identity
    published_at: datetime | None = None
    published_by: UUID | None = None

    @model_validator(mode="after")
    def _its_shape(self) -> Self:
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("a version names a model role once")
        keys = [row.key for row in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("a version holds one row a key")
        unserved = sorted(
            {row.key.role for row in self.rows if row.key.role is not None} - set(self.roles)
        )
        if unserved:
            raise ValueError(f"a row names a model role the version does not serve: {unserved}")
        published = self.status is MatrixStatus.PUBLISHED
        if published != (self.published_at is not None and self.published_by is not None):
            raise ValueError("a version is published exactly when it says when and by whom")
        return self

    def roles_of(self, row: MatrixRow) -> tuple[ModelRole, ...]:
        """The model roles a row serves: the one it names, or every one the
        version serves."""
        return self.roles if row.key.role is None else (row.key.role,)
