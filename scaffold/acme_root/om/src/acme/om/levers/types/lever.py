"""A lever: a text a tenant customizes its agents with, an agent playbook or a
reviewed agent knowledge entry, read for what misleads or stalls an agent before
a person publishes it, and read back from the sessions that spun after it.

A finding advises: it is recorded with the version it read and shown to
the person beside their publish, and it never refuses one. A reading
ranks the levers present in a tenant's sessions that spun against those
that did not, and names the sessions behind each figure."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.agent_steps.types.content import Stored
from acme.om.base import OmBase

MAX_DETAIL = 500
"""The most characters a finding quotes or says: a lever is a person's
text, so what is kept of it beside the version stays small."""


class LeverKind(StrEnum):
    AGENT_PLAYBOOK = "agent_playbook"  # a version a principal invokes into a session
    AGENT_KNOWLEDGE = "agent_knowledge"  # a reviewed entry a session recalls


class LeverCheck(StrEnum):
    """What a check found in a lever's text."""

    REPEATED_PHRASE = (
        "repeated_phrase"  # a phrase repeated past the bound: lingo read as load-bearing
    )
    CONTRADICTION = "contradiction"  # a must and a must-not on one subject
    UNKNOWN_NAME = "unknown_name"  # a tool or a kind no kind it reaches holds
    UNBOUNDED_RETRY = "unbounded_retry"  # an instruction to retry with no stopping condition
    PAST_SESSION_BOUND = "past_session_bound"  # longer than a session holds whole


class LeverFinding(OmBase):
    """One finding: the check that found it, what it found in a sentence,
    and the words of the text it stands on, cut to `MAX_DETAIL`."""

    check: LeverCheck
    detail: Stored = Field(min_length=1, max_length=MAX_DETAIL)
    excerpt: Stored | None = Field(default=None, max_length=MAX_DETAIL)


class LeverReach(OmBase):
    """What the kinds a lever reaches hold: their tools and their names. A
    agent playbook or an agent knowledge entry reaches every kind of its tenant."""

    tools: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()


class LeverRef(OmBase):
    """One version of a lever, as a session reached it: an agent playbook
    version's id, or an agent knowledge entry's id, and its version. Never its
    name or its slug, which are the tenant's words: an operator who reads
    sees the shape of what a session reached, never what it says."""

    kind: LeverKind
    id: UUID
    version: int = Field(ge=1)


class SpinTally(OmBase):
    """What a session's recorded steps say of a stall, read from their
    headers alone, never from what they say.

    `repeated_calls` counts the runs of one call made again and again, the
    same tool with the same input, and `repeated_failures` the runs of one
    call failing again and again, each run once it reaches its length.
    `same_requests` counts the model requests sent again unchanged after
    the provider answered them; `nudges` the turns that called no tool and
    earned the engine's nudge; `guards` the parks on the step guard or the
    deadline; and `inconclusive` the loops a bound ended without a
    conclusion."""

    repeated_calls: int = Field(default=0, ge=0)
    repeated_failures: int = Field(default=0, ge=0)
    same_requests: int = Field(default=0, ge=0)
    nudges: int = Field(default=0, ge=0)
    guards: int = Field(default=0, ge=0)
    inconclusive: int = Field(default=0, ge=0)

    @property
    def spun(self) -> bool:
        return any(
            (
                self.repeated_calls,
                self.repeated_failures,
                self.same_requests,
                self.nudges,
                self.guards,
                self.inconclusive,
            )
        )


class SessionLevers(OmBase):
    """One session of a reading: what its steps say of a stall, and the
    levers it reached."""

    agent_session_id: UUID
    spin: SpinTally
    levers: tuple[LeverRef, ...] = ()


class LeverStanding(OmBase):
    """A lever against the window: of the sessions it reached, how many
    spun, against the sessions it did not reach, and the sessions that
    spun with it, the first `most` of them."""

    lever: LeverRef
    sessions: int = Field(ge=1)
    spun: int = Field(ge=1)
    sessions_without: int = Field(ge=1)
    spun_without: int = Field(ge=0)
    spun_sessions: tuple[UUID, ...]

    @property
    def lift(self) -> float:
        """How much more often a session spun with the lever than without."""
        return self.spun / self.sessions - self.spun_without / self.sessions_without


class LeverReading(OmBase):
    """The levers of one tenant's sessions created in a window, best first,
    and how many sessions it read and how many of them stalled.
    `complete` is False when the window held more sessions, or a session
    more steps, than a reading reads, and the figures stand on what it
    read."""

    since: datetime
    until: datetime
    sessions: int = Field(ge=0)
    spun: int = Field(ge=0)
    complete: bool
    standings: tuple[LeverStanding, ...] = ()
