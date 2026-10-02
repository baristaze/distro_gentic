"""The results contract: the platform defines the protocol, never the
runner. A check is declared; a run writes a strict, versioned results
stream, one JSON object a line, and its cases stream as they finish."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from acme.om.base import FrozenMapping, Platform
from acme.om.evidence.types.provenance import ArtifactRef, Dependency
from acme.om.evidence.types.record import NAME, VERSION, Environment, RunOutcome

SCHEMA = 1
"""The results schema this platform writes and reads."""
SCHEMAS = frozenset({SCHEMA})
"""Every results schema the one collector reads."""


class CheckDeclaration(Platform):
    """A check as a project declares it: its name and version, the command
    template a runner is started with, its kind, the capabilities a place
    must offer to run it, and the version of the results schema it writes.
    `{version}` and `{out}` in the template are the version under test and
    where the results stream goes."""

    name: str = Field(pattern=NAME)
    version: str = Field(pattern=VERSION)
    command: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        min_length=1, max_length=50
    )
    kind: str = Field(pattern=NAME)
    capabilities: tuple[Annotated[str, Field(pattern=NAME)], ...] = ()
    schema_version: int = Field(ge=1)


class Offer(Platform):
    """What a place to run checks offers: its capabilities, and the results
    schemas its runner writes."""

    capabilities: frozenset[str] = frozenset()
    schemas: frozenset[int] = frozenset()


class CaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StartLine(Platform):
    """The first line of a run: what ran, at which version, under what."""

    kind: Literal["start"]
    schema_version: Literal[1]
    check: str = Field(pattern=NAME)
    check_version: str = Field(pattern=VERSION)
    version: str = Field(pattern=VERSION)
    dirty: bool
    environment: Environment
    host: str = Field(min_length=1, max_length=200)
    isolation: str = Field(min_length=1, max_length=100)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)
    dependencies: tuple[Dependency, ...] = ()
    started_at: datetime


class CaseLine(Platform):
    """One case, written as it finishes."""

    kind: Literal["case"]
    name: str = Field(min_length=1, max_length=500)
    outcome: CaseOutcome
    seconds: float = Field(ge=0)


class EndLine(Platform):
    """The last line of a run: how it ended, and what it measured and made."""

    kind: Literal["end"]
    outcome: RunOutcome
    finished_at: datetime
    metrics: FrozenMapping = Field(default_factory=dict, validate_default=True)
    artifacts: tuple[ArtifactRef, ...] = ()
    abort: str | None = Field(default=None, min_length=1, max_length=500)


ResultsLine = Annotated[StartLine | CaseLine | EndLine, Field(discriminator="kind")]
