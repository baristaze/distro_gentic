"""Pure rules of levers: the checks that read a lever's text before a
person publishes it, the stall a session's recorded steps show, and the
ranking of the levers the sessions that stalled reached. Values in, values
out: no check calls a model, so a publish spends nothing, and none runs
what it reads.

Every check is a heuristic. It finds what a person would want to look at
again, and a finding never refuses a publish. Each one reads a text of at
most a lever's bound in time linear in its length, whatever it holds."""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from acme.integrations.model_providers.types import StopReason
from acme.om.agent_sessions.limits import DEADLINE_UNLOCK, STEP_GUARD_UNLOCK
from acme.om.agents.types.kind import AgentKind, AgentKindCatalog
from acme.om.levers.types.lever import (
    MAX_DETAIL,
    LeverCheck,
    LeverFinding,
    LeverReach,
    LeverRef,
    LeverStanding,
    SessionLevers,
    SpinTally,
)
from acme.om.models.types.fill import MAIN
from acme.om.steps.types.header import (
    LoopEndedHeader,
    LoopOutcome,
    ModelRequestHeader,
    ModelResponseHeader,
    ParkedHeader,
    ParkReason,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Actor, Origin, StepType
from acme.om.trust.types.shape import StepShape

MOST_PER_CHECK = 5
"""The most findings one check answers for one text: past a few, a person
has seen the pattern."""

PHRASE_SHORTEST = 3
PHRASE_LONGEST = 6
REPEAT_FLOOR = 4
REPEAT_PER_WORDS = 500
"""A phrase of three to six words, two of them carrying meaning, said more
than `REPEAT_FLOOR` times, or more than once for every `REPEAT_PER_WORDS`
words of a longer text: an agent reads a phrase said that often as one
that matters more than the rest."""

SUBJECT_WORDS = 2
"""The words an instruction's subject is known by: the first two that carry
meaning after its must or its must-not."""

RUN = 3
"""The run of one call, or of its failures, that counts as a stall: the
engine tells the model of a repeated failure at the third."""

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|\n+")
TICKED = re.compile(r"`([a-z][a-z0-9_]{0,63})`")
LAST_WORD = re.compile(r"([a-z-]+)\W*$")
FIRST_WORD = re.compile(r"\W*([a-z-]+)")

STOP = frozenset(
    """a an the to of in on at for with by from and or but be is are was were it its
    this that these those you your we our they their i me my any all also only just
    ever then so as if not no do does did can could will would should must shall may
    might have has had been being into onto over under than when while each every
    always never sure make ensure avoid there here what which who whom""".split()
)
"""Words that carry no meaning of their own, for a phrase and a subject."""

NEGATIVE = re.compile(
    r"\b(?:must not|must never|mustn't|should not|should never|shouldn't|shall not|"
    + r"never|do not|don't|does not|doesn't|cannot|can't|may not|avoid)\b"
)
POSITIVE = re.compile(r"\b(?:must|always|should|shall|make sure to|be sure to|ensure)\b")

RETRY = re.compile(
    r"\b(?:keep (?:on )?(?:trying|retrying|going|running|polling|looping|calling|asking)"
    + r"|(?:retry|try again|repeat|loop|poll|rerun|re-run) until"
    + r"|always (?:retry|try again|rerun|re-run)"
    + r"|retry (?:forever|indefinitely|endlessly)"
    # Not to stop at all, never not to stop something: "do not stop the
    # database" names what to leave running.
    + r"|(?:do not|don't|never) (?:stop|give up|quit)"
    + r"(?=\s*(?:$|[.,;:!?)]|until\b|till\b|trying\b|retrying\b|going\b|working\b))"
    + r"|as many times as (?:it takes|needed|necessary|you need|required)"
    + r"|no matter how many (?:times|tries|attempts))\b"
)
BOUNDED = re.compile(
    r"\b(?:at most|up to|no more than|not more than|maximum|max|limit|limits|budget"
    + r"|give up after|stop after|once|twice|times|attempts|tries|minutes?|hours?|seconds?)\b"
    + r"|\d"
)

TOOL_WORDS = frozenset({"tool", "tools"})
KIND_WORDS = frozenset({"kind", "kinds", "agent", "agents", "sub-agent", "sub-agents"})


def cut(text: str, most: int = MAX_DETAIL) -> str:
    """`text` on one line, at most `most` characters, an ellipsis where it
    was cut."""
    flat = " ".join(text.split())
    return flat if len(flat) <= most else flat[: most - 1] + "…"


def reach_of(catalog: AgentKindCatalog) -> LeverReach:
    """What a lever of the tenant reaches: the latest version of every kind
    its sessions start on, their tools and their names."""
    latest: dict[str, AgentKind] = {}
    for kind in catalog.kinds:
        held = latest.get(kind.name)
        if held is None or kind.version > held.version:
            latest[kind.name] = kind
    return LeverReach(
        tools=frozenset(tool for kind in latest.values() for tool in kind.tools),
        kinds=frozenset(latest),
    )


def checked(
    text: str,
    reach: LeverReach,
    *,
    bound: int | None = None,
    size: int | None = None,
    tools: Iterable[str] = (),
) -> tuple[LeverFinding, ...]:
    """What the checks find in a lever's text, the words a person wrote: a
    phrase repeated past the bound, a must and a must-not on one subject, a
    tool or a kind no kind it reaches holds (among them each of `tools`,
    the tools it names outside its text, such as an agent playbook's gates), an
    instruction to retry with no stopping condition, and, where the lever
    has one, a size past `bound`, the characters a session holds of it
    whole. `size` is the characters a session receives, the text's own
    when it is None."""
    plain = text.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    sentences = [s for s in SENTENCE_END.split(plain) if s.strip()]
    return (
        *repeated_phrases(WORD.findall(plain.lower())),
        *contradictions(sentences),
        *unknown_names(plain, reach, tools),
        *unbounded_retries(sentences),
        *past_bound(len(plain) if size is None else size, bound),
    )


def repeated_phrases(words: Sequence[str]) -> list[LeverFinding]:
    bound = max(REPEAT_FLOOR, len(words) // REPEAT_PER_WORDS)
    found: list[tuple[str, int]] = []
    for size in range(PHRASE_LONGEST, PHRASE_SHORTEST - 1, -1):
        counts = Counter(tuple(words[at : at + size]) for at in range(len(words) - size + 1))
        for phrase, count in counts.most_common():
            if count <= bound:
                break
            if sum(word not in STOP for word in phrase) < 2:
                continue
            said = " ".join(phrase)
            # A phrase inside a longer one found already is the same lingo.
            if any(f" {said} " in f" {longer} " for longer, _ in found):
                continue
            found.append((said, count))
            if len(found) >= MOST_PER_CHECK * 10:
                break
    found.sort(key=lambda phrase: -phrase[1])
    return [
        LeverFinding(
            check=LeverCheck.REPEATED_PHRASE,
            detail=cut(
                f"“{said}” comes {count} times, past {bound}: an agent reads a phrase "
                + "said that often as one that matters more than the rest"
            ),
            excerpt=cut(said),
        )
        for said, count in found[:MOST_PER_CHECK]
    ]


def _subject(rest: str) -> tuple[str, ...] | None:
    meaning = [word for word in WORD.findall(rest.lower()) if word not in STOP]
    return tuple(meaning[:SUBJECT_WORDS]) if len(meaning) >= SUBJECT_WORDS else None


def contradictions(sentences: Sequence[str]) -> list[LeverFinding]:
    told: dict[tuple[str, ...], tuple[list[str], list[str]]] = {}
    for sentence in sentences:
        lowered = sentence.lower()
        negative = NEGATIVE.search(lowered)
        positive = POSITIVE.search(lowered)
        if negative is not None and (positive is None or negative.start() <= positive.start()):
            subject, side = _subject(lowered[negative.end() :]), 1
        elif positive is not None:
            subject, side = _subject(lowered[positive.end() :]), 0
        else:
            continue
        if subject is not None:
            told.setdefault(subject, ([], []))[side].append(sentence.strip())
    found: list[LeverFinding] = []
    for subject, (musts, must_nots) in told.items():
        if musts and must_nots:
            found.append(
                LeverFinding(
                    check=LeverCheck.CONTRADICTION,
                    detail=cut(
                        f"one instruction says to “{' '.join(subject)}” and another "
                        + "says never to: an agent told both goes back and forth"
                    ),
                    excerpt=cut(f"{musts[0]} / {must_nots[0]}"),
                )
            )
    return found[:MOST_PER_CHECK]


def _named(text: str, start: int, end: int) -> str | None:
    """What the words beside a name in backticks say it is: a tool, a kind,
    or neither."""
    before = LAST_WORD.search(text[max(0, start - 24) : start].lower())
    after = FIRST_WORD.match(text[end : end + 24].lower())
    beside = {match.group(1) for match in (before, after) if match is not None}
    if beside & TOOL_WORDS:
        return "tool"
    if beside & KIND_WORDS:
        return "kind"
    return None


def unknown_names(text: str, reach: LeverReach, tools: Iterable[str]) -> list[LeverFinding]:
    """A name in backticks, spelled as a tool is, that the words beside it
    call a tool or a kind, and that no kind the lever reaches holds; and
    each of `tools` none of them holds. A name in backticks the words
    beside it do not call either, such as `DATABASE_URL` or `max_retries`,
    is a word the person quotes, never a tool. A lever that reaches no
    kind, in a process that registers none, has nothing to be read
    against, and this check says nothing of it."""
    if not reach.kinds:
        return []
    unknown: dict[str, str] = {}
    for tool in tools:
        if tool not in reach.tools:
            unknown.setdefault(tool, "tool")
    for match in TICKED.finditer(text):
        name = match.group(1)
        said = _named(text, match.start(), match.end())
        if said == "tool" and name not in reach.tools:
            unknown.setdefault(name, "tool")
        elif said == "kind" and name not in reach.kinds:
            unknown.setdefault(name, "kind")
    return [
        LeverFinding(
            check=LeverCheck.UNKNOWN_NAME,
            detail=cut(
                f"names the {what} “{name}”, which no kind it reaches holds: "
                + "an agent asked to use it looks for it and fails"
            ),
            excerpt=cut(name),
        )
        for name, what in list(unknown.items())[:MOST_PER_CHECK]
    ]


def unbounded_retries(sentences: Sequence[str]) -> list[LeverFinding]:
    found: list[LeverFinding] = []
    for sentence in sentences:
        lowered = sentence.lower()
        retry = RETRY.search(lowered)
        if retry is None:
            continue
        rest = lowered[: retry.start()] + " " + lowered[retry.end() :]
        if BOUNDED.search(rest) is None:
            found.append(
                LeverFinding(
                    check=LeverCheck.UNBOUNDED_RETRY,
                    detail=cut(
                        f"“{retry.group(0)}” with no stopping condition: an agent "
                        + "told to go on until it works repeats the same call"
                    ),
                    excerpt=cut(sentence),
                )
            )
    return found[:MOST_PER_CHECK]


def past_bound(size: int, bound: int | None) -> list[LeverFinding]:
    if bound is None or size <= bound:
        return []
    return [
        LeverFinding(
            check=LeverCheck.PAST_SESSION_BOUND,
            detail=cut(
                f"{size} characters, past the {bound} a session holds whole: "
                + "once it summarizes, it keeps only an excerpt of the rest"
            ),
        )
    ]


@dataclass
class _Loop:
    """Where one loop's runs stand as its steps are read."""

    last_call: tuple[str, str] | None = None
    calls: int = 0
    failing: tuple[str, str] | None = None
    failures: int = 0
    last_prompt: str | None = None
    last_request: UUID | None = None
    answered: bool = False
    accepted: bool = False
    turned: bool = False  # the step before was a whole turn of the model
    requests: dict[UUID, tuple[str, str]] = field(default_factory=dict[UUID, tuple[str, str]])


def spin_of(steps: Iterable[StepShape]) -> SpinTally:
    """What a session's steps say of a stall, read from their headers alone,
    each loop's in `seq` order, as the engine's own limits read them."""
    counts = Counter[str]()
    loops: dict[UUID, _Loop] = {}
    for step in sorted(steps, key=lambda shape: shape.seq):
        loop = loops.setdefault(step.loop_id, _Loop())
        header = step.header
        turned, loop.turned = loop.turned, False
        if isinstance(header, ToolRequestHeader):
            call = (header.tool, header.input_hash)
            loop.calls = loop.calls + 1 if call == loop.last_call else 1
            loop.last_call = call
            loop.requests[step.id] = call
            if loop.calls == RUN:
                counts["repeated_calls"] += 1
        elif isinstance(header, ToolResponseHeader):
            failed = header.failure is not None
            call = loop.requests.get(step.responds_to) if step.responds_to else None
            if failed and call is not None:
                loop.failures = loop.failures + 1 if call == loop.failing else 1
                loop.failing = call
                if loop.failures == RUN:
                    counts["repeated_failures"] += 1
            elif not failed:
                loop.failing, loop.failures = None, 0
            if header.accepted is not None and header.accepted.outcome is LoopOutcome.INCONCLUSIVE:
                loop.accepted = True
        elif isinstance(header, ModelRequestHeader) and header.role == MAIN:
            if loop.answered and header.prompt_hash == loop.last_prompt:
                counts["same_requests"] += 1
            loop.last_prompt, loop.last_request, loop.answered = header.prompt_hash, step.id, False
        elif isinstance(header, ModelResponseHeader):
            if step.responds_to == loop.last_request and header.stop_reason is not None:
                loop.answered = True
            loop.turned = not (
                header.truncated or header.abandoned or header.stop_reason is StopReason.PAUSE
            )
        elif step.type is StepType.MESSAGE and step.actor is Actor.ENGINE:
            # The engine's word right after a whole turn is the nudge a turn
            # that called no tool earns.
            if turned and step.origin is Origin.ENGINE:
                counts["nudges"] += 1
        elif isinstance(header, ParkedHeader):
            park = header.park
            if park.reason is ParkReason.PERSON and park.unlock in (
                STEP_GUARD_UNLOCK,
                DEADLINE_UNLOCK,
            ):
                counts["guards"] += 1
            if park.reason is ParkReason.CHILDREN:
                loop.last_call, loop.calls = None, 0
        elif isinstance(header, LoopEndedHeader):
            if header.outcome is LoopOutcome.INCONCLUSIVE and not loop.accepted:
                counts["inconclusive"] += 1
    return SpinTally.model_validate(dict(counts))


def standings(sessions: Sequence[SessionLevers], most: int) -> tuple[LeverStanding, ...]:
    """The levers that came before a stall more often than its absence did,
    best first: for each, how often the sessions that reached it spun
    against those that did not, and the first `most` of its sessions that
    spun. A lever every session reached has nothing to stand against, and
    ranks nowhere; nor does one no more often present where sessions spun."""
    total = len(sessions)
    spun_total = sum(1 for session in sessions if session.spin.spun)
    held: dict[LeverRef, list[SessionLevers]] = {}
    for session in sessions:
        for lever in dict.fromkeys(session.levers):
            held.setdefault(lever, []).append(session)
    ranked: list[LeverStanding] = []
    for lever, reached in held.items():
        spun = [session.session_id for session in reached if session.spin.spun]
        without = total - len(reached)
        if without == 0 or not spun:
            continue
        standing = LeverStanding(
            lever=lever,
            sessions=len(reached),
            spun=len(spun),
            sessions_without=without,
            spun_without=spun_total - len(spun),
            spun_sessions=tuple(spun[:most]),
        )
        if standing.lift > 0:
            ranked.append(standing)
    ranked.sort(
        key=lambda standing: (
            -standing.lift,
            -standing.spun,
            standing.lever.kind.value,
            str(standing.lever.id),
            standing.lever.version,
        )
    )
    return tuple(ranked)


def id_floor(at: datetime) -> UUID:
    """The least v7 id of the millisecond `at`: every id minted before it
    sorts below it."""
    millis = int(at.timestamp() * 1000) & ((1 << 48) - 1)
    return UUID(int=(millis << 80) | (0x7 << 76) | (0b10 << 62))
