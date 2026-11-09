"""The results contract: the platform defines the protocol, never the
runner. A check is declared; a run writes a strict, versioned results
stream, one JSON object a line, and its cases stream as they finish."""

from datetime import datetime
from enum import StrEnum
from string import Formatter
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from acme.om.base import FrozenMapping, OmBase
from acme.om.evidence.types.provenance import ArtifactRef, Dependency
from acme.om.evidence.types.record import NAME, VERSION, RunImage, RunOutcome

SCHEMA = 1
"""The results schema this platform writes and reads."""
SCHEMAS = frozenset({SCHEMA})
"""Every results schema the one collector reads."""
PLATFORM_EXECUTOR = "platform"
"""The platform's fresh executor, by name: where a check that names no
other runs."""
FIELDS = frozenset({"version", "out", "work"})
"""The fields a check's command templates name: the version under test,
where the results stream goes, and the folder the head's own part writes
in."""


class CheckDeclaration(OmBase):
    """A check as an agent project declares it: its name and version, the command
    template a runner is started with, its kind, the capabilities a place
    must offer to run it, the version of the results schema it writes, and
    the executor that runs it, by name: the platform's fresh executor,
    or one a product registered at its root.
    `{version}` and `{out}` in the template are the version under test and
    where the results stream goes.

    A check whose runner must never load the head's code declares `head`:
    the command that runs it, apart. The fresh executor runs it first, in
    the tree, as a user of its own, who writes no file the run protects,
    never the results stream, and nowhere in the tree; `{work}` is a folder
    of its trial's own that it writes in. The runner then runs as the
    instance's own user, in a copy of the files the run protects, never in
    the tree, and scores what the head's part left in `{work}`. What each
    part runs is the check's own, so its author keeps the rest: the head's
    part leaves answers, never verdicts, since the head's code decides
    whatever is decided there; and the runner never imports or runs the
    head's code, nor what `{work}` holds, since that code would run as the
    runner's user and could write a passing result.

    The templates are checked when they are declared: each parses and names
    those fields alone, each bare; `command` names `{out}`, so a runner it
    starts always writes its results; `head` never names it; and only a
    check that declares `head` names `{work}`."""

    name: str = Field(pattern=NAME)
    version: str = Field(pattern=VERSION)
    command: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        min_length=1, max_length=50
    )
    kind: str = Field(pattern=NAME)
    capabilities: tuple[Annotated[str, Field(pattern=NAME)], ...] = ()
    schema_version: int = Field(ge=1)
    executor: str = Field(default=PLATFORM_EXECUTOR, pattern=NAME)
    head: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        default=(), max_length=50
    )

    @model_validator(mode="after")
    def _templates_a_runner_fills(self) -> Self:
        named = {field for argument in self.command for field in _fields(argument)}
        apart = {field for argument in self.head for field in _fields(argument)}
        if "out" not in named:
            raise ValueError("the command names {out}, where the results stream goes")
        if "out" in apart:
            raise ValueError("the head's command never names {out}: only the runner writes it")
        if "work" in named | apart and not self.head:
            raise ValueError("only a check that runs the head apart names {work}")
        return self


class Offer(OmBase):
    """What a place to run checks offers: its capabilities, and the results
    schemas its runner writes."""

    capabilities: frozenset[str] = frozenset()
    schemas: frozenset[int] = frozenset()


class CaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StartLine(OmBase):
    """The first line of a run: what ran, at which version, under what."""

    kind: Literal["start"]
    schema_version: Literal[1]
    check: str = Field(pattern=NAME)
    check_version: str = Field(pattern=VERSION)
    version: str = Field(pattern=VERSION)
    dirty: bool
    environment: RunImage
    host: str = Field(min_length=1, max_length=200)
    isolation: str = Field(min_length=1, max_length=100)
    parameters: FrozenMapping = Field(default_factory=dict, validate_default=True)
    dependencies: tuple[Dependency, ...] = ()
    started_at: datetime


class CaseLine(OmBase):
    """One case, written as it finishes."""

    kind: Literal["case"]
    name: str = Field(min_length=1, max_length=500)
    outcome: CaseOutcome
    seconds: float = Field(ge=0)


class EndLine(OmBase):
    """The last line of a run: how it ended, and what it measured and made."""

    kind: Literal["end"]
    outcome: RunOutcome
    finished_at: datetime
    metrics: FrozenMapping = Field(default_factory=dict, validate_default=True)
    artifacts: tuple[ArtifactRef, ...] = ()
    abort: str | None = Field(default=None, min_length=1, max_length=500)


ResultsLine = Annotated[StartLine | CaseLine | EndLine, Field(discriminator="kind")]


def _fields(argument: str) -> set[str]:
    """The fields one argument of a command template names. An argument
    that does not parse, or that names any other field, or one with a
    conversion or a format of its own, is refused."""
    try:
        parsed = list(Formatter().parse(argument))
    except ValueError as error:
        raise ValueError(f"the command argument {argument!r} does not parse: {error}") from None
    named: set[str] = set()
    for _, field, spec, conversion in parsed:
        if field is None:
            continue
        if field not in FIELDS or spec or conversion:
            raise ValueError(
                f"the command argument {argument!r} names a field other than a bare "
                "{version}, {out}, or {work}"
            )
        named.add(field)
    return named
