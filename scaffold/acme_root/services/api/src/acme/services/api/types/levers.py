"""Wire types of the levers: what the checks found in a playbook version
or an agent knowledge entry, answered beside its publish or its review, and an
operator's reading of the levers a tenant's sessions reached before they
stalled."""

from datetime import datetime
from uuid import UUID

from acme.om.levers.types.lever import LeverCheck, LeverKind
from acme.services.api.types.common import View


class FindingView(View):
    """What one check found: advice for the person who published the
    lever, never a refusal. `excerpt` is the words it stands on."""

    check: LeverCheck
    detail: str
    excerpt: str | None


class LeverView(View):
    """One version of a lever as a session reached it, by its kind, its id,
    and its version: never its name or its slug, the tenant's words, which
    an operator who reads never sees."""

    kind: LeverKind
    id: UUID
    version: int


class LeverStandingView(View):
    """A lever against the window: of the sessions that reached it, how
    many stalled, against the sessions that did not; `lift` is the first
    rate less the second; and the sessions that stalled with it, the first
    of them."""

    lever: LeverView
    sessions: int
    spun: int
    sessions_without: int
    spun_without: int
    lift: float
    spun_sessions: list[UUID]


class LeverReadingView(View):
    """The levers of one tenant's sessions created in `[since, until)`, best
    first. `complete` is false when the window held more sessions, or a
    session more steps, than one reading reads."""

    since: datetime
    until: datetime
    sessions: int
    spun: int
    complete: bool
    standings: list[LeverStandingView]
