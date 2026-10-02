"""Acceptance judges an agent's work the way the gate does, and more. The
objective hides its root cause, a hidden suite must pass beside the
visible one, the checks and the system under test stay untouched, no
surface the agent reads mentions the hidden suite, and the chain of
evidence is judged, never the presence of files."""

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.policy import PATTERN
from acme.om.evidence.types.record import NAME, PROJECT, VERSION, ExecutionRecord


class Surface(StrEnum):
    """Every kind of text an agent reads. A scan covers each of them."""

    PROMPT = "prompt"
    KNOWLEDGE = "knowledge"
    TOOL_SOURCE = "tool_source"
    EVIDENCE = "evidence"
    PULL_REQUEST = "pull_request"


class Leak(Platform):
    """A mention of the hidden suite where the agent can read it: the
    surface, the item in it, and the marker it holds."""

    surface: Surface
    item: str = Field(min_length=1)
    marker: str = Field(min_length=1)


class HiddenSuite(Platform):
    """The checks acceptance runs beside the visible ones, which the agent
    never sees, and the markers a scan looks for: the suite's name, its
    paths, its case names. Its checks run on a fresh executor at the head
    delivered, and their runs stay with the verdict, never with the
    session's evidence, which the agent reads.

    It lives in a source of its own (`source`), never in the project's
    repository: a protected path is write-denied, not read-denied, so a
    suite in the tree the workspace checks out is one the agent can read
    and fit its fix to. The executor fetches it only to run it."""

    source: str = Field(pattern=VERSION)
    checks: tuple[CheckDeclaration, ...] = Field(min_length=1, max_length=50)
    markers: tuple[str, ...] = Field(min_length=1, max_length=200)


class Scenario(Platform):
    """One acceptance scenario: the project and the version the work starts
    from, the objective the agent reads, the markers of the root cause it
    hides, the checks of the project's policy the baseline must fail on, the
    hidden suite, and the paths no change may touch: the checks, visible
    and hidden, and the system under test."""

    name: str = Field(pattern=NAME)
    project: str = Field(pattern=PROJECT)
    base: str = Field(pattern=VERSION)
    objective: str = Field(min_length=1, max_length=20_000)
    root_cause: tuple[str, ...] = Field(min_length=1, max_length=50)
    visible: tuple[str, ...] = Field(min_length=1, max_length=50)
    hidden: HiddenSuite
    forbidden: tuple[PATTERN, ...] = Field(min_length=1, max_length=200)


class Link(StrEnum):
    """The links of the chain of evidence the harness judges. Each one is a
    record the platform wrote, never a file the agent made."""

    BASELINE = "baseline"  # a baseline at the base, run before the change, that fails
    HYPOTHESES = "hypotheses"  # every hypothesis stated is resolved by a finding
    VALIDATION = "validation"  # the gate accepts the success, verified, at a clean head
    REPORT = "report"  # the result cites the runs of the validation at the head
    HIDDEN = "hidden"  # the hidden suite passes at the head
    UNTOUCHED = "untouched"  # no check and nothing of the system under test changed
    UNMENTIONED = "unmentioned"  # no surface the agent reads names the hidden suite


class Break(Platform):
    """A link the chain lacks, and why."""

    link: Link
    reason: str = Field(min_length=1)


class AcceptanceVerdict(Identifiable, Created):
    """What the harness found of one session's work on one scenario: the
    head it judged, each link the chain lacks, and the hidden suite's runs,
    kept here and nowhere the agent reads. It passed only with no break."""

    scenario: str = Field(pattern=NAME)
    session_id: UUID
    head: str | None = Field(default=None, pattern=VERSION)
    breaks: tuple[Break, ...] = ()
    hidden: tuple[ExecutionRecord, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.breaks

    @property
    def score(self) -> float:
        """The judged score a benchmark keeps: the share of the chain's links
        held, so a chain one link short scores under a whole one and over
        one that holds nothing."""
        return 1 - len(self.broken()) / len(Link)

    def broken(self) -> frozenset[Link]:
        return frozenset(found.link for found in self.breaks)
