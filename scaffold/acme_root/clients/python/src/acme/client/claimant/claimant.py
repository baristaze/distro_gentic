"""A product's claimant on the platform's path for every claimant kind
(ADR 2029), with no credential code of its own. It enrolls once, or picks
up its credential, through `/claimants/...`. Each turn it rotates the
credential when due, sends the reports its journal keeps, and claims the
next item of its kind, while it has room for one. While a report waits
for the platform, it claims nothing. It renews the lease on an item it
holds, and reports it: the report is kept in the journal before it is
sent, so a report the platform did not answer is sent once it answers,
and one it recorded is never sent again.

An item claimed again whose report the journal keeps from an earlier
claim is answered with that report, under the new claim, and never handed
to the work a second time. A kind that reports through calls of its own
gives its own `send`, and keeps its entries with `keep`; the journal, the
order, and the outcomes are the same.

A turn rotates the credential only between works, so a work longer than
half the credential's life would outlive it. A work runs inside
`keeping_alive`, which rotates the credential when due every beat while
the work runs.

Beside its turns it holds its control stream open (`listening`), as a host
does: a wake there cuts the wait between turns short, so work is claimed
as it lands and the wait is only the slow fallback; a revoke ends what
still works on an item the platform took back (`revoked`), and no report
of that work is kept; and an append to a stream its kind reads wakes the
work that reads it (`appended`)."""

import asyncio
import contextlib
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from acme.client.claimant.enrollment import (
    ClientFactory,
    CredentialRefused,
    Enrollment,
    RoutesClaimantImpl,
    refused,
)
from acme.client.claimant.journal import Entry, Journal
from acme.client.claimant.settings import ClaimantSettings
from acme.client.client import ApiClient
from acme.client.transport import WIRE_FAILURES, ApiError
from acme.client.types.hosts import ClaimantControlKind, ClaimantControlView, ClaimantWorkView
from acme.client.types.placement import ReportOutcome
from acme.timing import Retries, RetryPolicy

log = logging.getLogger(__name__)

RETRY = RetryPolicy(base=1.0, cap=120.0, jitter=0.5)
"""The wait after a failure a claimant outlasts: an answer the platform
could not serve, a 429, or the wire. It doubles per failure in a row from
1 s, half of it jitter, so claimants that failed together do not return
together; it is longer when the server asked for longer, and never past
120 s, a 429's ask included. A caller that asks again sooner names its
own cap."""

REOPEN = RetryPolicy(base=2.0, cap=2.0, jitter=0.5)
"""The pause before the next control stream once the platform ended one:
2 s at most, half of it jitter, as a host's."""

CONTROL_ITEMS = 64
"""The most items the claimant names as it opens its control stream, the
platform's own bound: the last ones it was handed."""

CLAIM_LOST = frozenset({404, 409})
"""A report's answers when the item is no longer this claim's: its claim
lapsed, or it settled."""

REASON_MAX = 500
"""The longest reason the platform records for a failure."""

NO_REASON = "failed with no reason given"
"""A failure's reason when the work gave a blank one."""

Sender = Callable[[ApiClient, Entry], Awaitable[Any]]
"""Sends one kept report with the claimant's client."""


async def send_report(client: ApiClient, entry: Entry) -> None:
    """The platform's own report of an item: done, or failed with why."""
    await client.report_claimant_work(UUID(entry.item_id), entry.body)


class Sent(Enum):
    RECORDED = "recorded"
    LAPSED = "lapsed"
    SET_ASIDE = "set_aside"


@dataclass
class _Held:
    """What the control stream said of one item the claimant was handed:
    that the platform took it back, and which of the streams its kind reads
    gained entries since the work last waited on each."""

    revoked: asyncio.Event = field(default_factory=asyncio.Event)
    appended: dict[str, asyncio.Event] = field(default_factory=dict[str, asyncio.Event])

    def stream(self, kind: str) -> asyncio.Event:
        return self.appended.setdefault(kind, asyncio.Event())


@dataclass(frozen=True)
class Turn:
    """What one turn handed the work, and the wait before the next turn."""

    item: ClaimantWorkView | None
    wait: float


class Claimant:
    def __init__(
        self,
        settings: ClaimantSettings,
        client_for: ClientFactory,
        *,
        send: Sender = send_report,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self.enrollment = Enrollment(settings, RoutesClaimantImpl(), client_for, now)
        self.journal = Journal(settings.journal_path)
        self._send = send
        self._draw = random.random if jitter is None else jitter
        self._retries = Retries(RETRY, draw=self._draw)
        self.woken = asyncio.Event()
        """Set when the control stream says work reached the claimant's
        lanes, or once its credential is refused."""
        self._held: dict[UUID, _Held] = {}

    async def start(self) -> None:
        """Enrolls once, or picks up the credential it holds."""
        await self.enrollment.start()

    def client(self) -> ApiClient:
        """A client with the claimant's credential as it is now, for its
        kind's own calls."""
        return self.enrollment.client()

    async def turn(self, *, claim: bool = True) -> Turn:
        """One turn, and how long to wait before the next: none when it
        handed out an item, a beat when there was none, and a growing wait
        after a failure it outlasts. A refused credential raises
        `CredentialRefused`, and every turn after it does too."""
        if self.enrollment.refused:
            raise CredentialRefused("the platform refused this claimant's credential")
        try:
            item = await self._tick(claim)
        except ApiError as error:
            if refused(error):
                self.enrollment.refuse()
                raise CredentialRefused(str(error)) from None
            log.warning("the platform failed: %s %s", error.status, error.code)
            return Turn(None, self._retries.failed(error.retry_after))
        except WIRE_FAILURES as error:
            log.warning("the platform is unreachable: %s", error)
            return Turn(None, self._retries.failed())
        self._retries.reset()
        return Turn(item, 0.0 if item is not None else self._settings.beat_seconds)

    async def wait(self, seconds: float) -> None:
        """Waits a turn's wait, cut short once the control stream wakes the
        claimant to claim; a wake heard during the turn holds. With no
        stream open it is the turn's wait, the slow fallback claim."""
        if seconds > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.woken.wait(), seconds)
        self.woken.clear()

    @contextlib.asynccontextmanager
    async def listening(self) -> AsyncIterator[None]:
        """Holds the control stream open beside what runs inside it, and
        opens it again whenever it ends, with the credential held then
        (`listen`). Once the platform ended one, it pauses as `REOPEN` says;
        once one failed, it waits as `RETRY` says, and a line heard starts
        that wait over. A refused credential stops it, and `woken` is set,
        so the next turn raises `CredentialRefused`."""
        beside = asyncio.create_task(self._listening())
        try:
            yield
        finally:
            beside.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beside

    async def listen(self, heard: Callable[[], None] = lambda: None) -> None:
        """One control stream, held open until the platform ends it with the
        credential it was opened with. It names the items the claimant
        works on, so one taken back while no stream was open is revoked at
        once. A wake sets `woken`; a revoke sets the item's `revoked`; an
        append wakes `appended` for the item and the stream's kind. `heard`
        is called on each line."""
        items = list(self._held)[-CONTROL_ITEMS:]
        await self._calling(lambda client: self._heard_all(client, items, heard))

    def revoked(self, item: ClaimantWorkView) -> asyncio.Event:
        """Set once the control stream says the platform no longer holds the
        item for this claimant: its lease was taken, or it was ended. The
        work on it stops then, and whatever it reports is not kept, a
        success as much as a failure (`keep`): the item runs again where
        it is claimed next, and a work cut short is never recorded done."""
        return self._hold(item.id).revoked

    async def appended(self, item: ClaimantWorkView, kind: str, seconds: float) -> bool:
        """Waits until the control stream says a stream of `kind`, one this
        claimant's kind reads, has new entries for the item, or `seconds`
        pass: whether it was woken. The work reads the stream after either,
        so `seconds` is its slow fallback read. An append heard since its
        last wait on the kind holds."""
        event = self._hold(item.id).stream(kind)
        try:
            await asyncio.wait_for(event.wait(), seconds)
        except TimeoutError:
            return False
        finally:
            event.clear()
        return True

    @contextlib.asynccontextmanager
    async def keeping_alive(self) -> AsyncIterator[None]:
        """Keeps the credential live while the work inside it runs: beside
        it, every beat, the credential is rotated when due, as a turn
        rotates it, and a failure it outlasts waits for the next beat. A
        work longer than half the credential's life would otherwise outlive
        it, and its report and every turn after would be refused. It stops
        once the work ends, or once the platform refuses the credential.

        A rotation under way when the work ends is finished before it
        returns, never cancelled: the platform ends the credential it
        rotated, and one it issued but the claimant never kept is lost.

        A work opens `claimant.client()` for each call or short burst and
        never holds one across a beat, since a rotation retires the token
        a held client carries a minute later, and its calls are refused."""
        ended = asyncio.Event()
        beside = asyncio.create_task(self._keep_alive(ended))
        try:
            yield
        finally:
            ended.set()
            await asyncio.shield(beside)

    async def renew(self, item: ClaimantWorkView) -> ClaimantWorkView:
        """Renews the lease on an item it holds. A failure is raised for
        the work to time against its lease (`LeaseClock`); a refused
        credential stops the claimant."""
        token = item.claim_token
        if token is None:
            raise ValueError(f"item {item.id} is held under no claim token")
        return await self._calling(lambda client: client.extend_claimant_lease(item.id, token))

    async def report(
        self, item: ClaimantWorkView, outcome: ReportOutcome, error: str | None = None
    ) -> bool:
        """The item's answer, kept in the journal, then sent: whether the
        platform recorded it. One it did not answer waits in the journal,
        and the next turn sends it. One for an item the control stream
        revoked is not kept (`keep`).

        It is held to the report's shape before it is kept, so the platform
        never refuses it for its reason: a failure names its reason and a
        success names none, or it raises `ValueError`; a blank reason is
        replaced by one that says so, and a long one is cut to
        `REASON_MAX`."""
        if item.claim_token is None:
            raise ValueError(f"item {item.id} is held under no claim token")
        if (outcome is ReportOutcome.failed) != (error is not None):
            raise ValueError("a failure names its reason, and a success names none")
        body: dict[str, Any] = {"claim_token": str(item.claim_token), "outcome": outcome.value}
        if error is not None:
            body["error"] = error[:REASON_MAX] if error.strip() else NO_REASON
        try:
            return await self.keep(Entry(str(item.id), str(item.id), body))
        finally:
            self._held.pop(item.id, None)

    async def keep(self, entry: Entry) -> bool:
        """Keeps a report in the journal, then sends it with `send`:
        whether the platform recorded it.

        A report of an item the control stream revoked is not kept, a
        success as much as a failure, and is answered False: the work on it
        was cut short, so the item runs again where it is claimed next, and
        no report of the stopped work lands under that claim. Running it
        twice is safe, since a handler is idempotent; recording a work cut
        short as done is not."""
        held = self._held.get(UUID(entry.item_id))
        if held is not None and held.revoked.is_set():
            log.warning("item %s was revoked; its report is not kept", entry.item_id)
            return False
        self.journal.keep(entry)
        try:
            return await self._sent(entry) is Sent.RECORDED
        except (ApiError, *WIRE_FAILURES) as failure:
            log.warning("report %s waits in the journal: %s", entry.key, failure)
            return False

    async def flush(self) -> bool:
        """Sends each report the journal keeps, oldest first: False while
        the platform does not answer one."""
        try:
            await self._flush()
        except (ApiError, *WIRE_FAILURES) as failure:
            log.warning("the journal waits: %s", failure)
            return False
        return True

    async def _listening(self) -> None:
        retries = Retries(RETRY, draw=self._draw)
        while not self.enrollment.refused:
            try:
                await self.listen(heard=retries.reset)
                wait = REOPEN.wait(1, draw=self._draw)
            except CredentialRefused:
                break
            except ApiError as error:
                if refused(error):
                    break
                log.warning("the control stream ended: %s %s", error.status, error.code)
                wait = retries.failed(error.retry_after)
            except WIRE_FAILURES as error:
                log.warning("the control stream ended: %s", error)
                wait = retries.failed()
            await asyncio.sleep(wait)
        self.woken.set()

    async def _heard_all(
        self, client: ApiClient, items: list[UUID], heard: Callable[[], None]
    ) -> None:
        async for message in client.claimant_control_stream(items):
            heard()
            self._heard(message)

    def _heard(self, message: ClaimantControlView) -> None:
        if message.kind is ClaimantControlKind.wake:
            self.woken.set()
            return
        held = None if message.item_id is None else self._held.get(message.item_id)
        if held is None:
            return  # an item it no longer works on: it reported it
        if message.kind is ClaimantControlKind.revoke:
            if not held.revoked.is_set():
                log.warning("item %s is no longer this claimant's", message.item_id)
            held.revoked.set()
        elif message.kind is ClaimantControlKind.appended and message.stream_kind is not None:
            held.stream(message.stream_kind).set()

    def _hold(self, item_id: UUID) -> _Held:
        return self._held.setdefault(item_id, _Held())

    async def _keep_alive(self, ended: asyncio.Event) -> None:
        while not self.enrollment.refused:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(ended.wait(), self._settings.beat_seconds)
            if ended.is_set():
                return
            try:
                await self.enrollment.rotate_if_due()
            except CredentialRefused:
                return
            except (ApiError, *WIRE_FAILURES) as error:
                log.warning("the credential's rotation failed: %s", error)

    async def _tick(self, claim: bool) -> ClaimantWorkView | None:
        await self.enrollment.rotate_if_due()
        await self._flush()
        if not claim:
            return None
        answer = await self._calling(lambda client: client.claim_claimant_work())
        item = answer.item
        if item is None or item.claim_token is None:
            return None
        kept = self.journal.lapsed(item.id)
        if kept is not None:
            # Its report waits from an earlier claim: it lands under this
            # one, and the work never runs again.
            again = kept.under(item.id, item.claim_token)
            self.journal.keep(again)
            await self._sent(again)
            return None
        self._held[item.id] = _Held()
        return item

    async def _flush(self) -> None:
        for entry in self.journal.pending():
            await self._sent(entry)

    async def _sent(self, entry: Entry) -> Sent:
        """Sends one kept report. A failure the claimant outlasts is
        raised, and the report stays in the journal."""
        try:
            await self._calling(lambda client: self._send(client, entry))
        except ApiError as error:
            if refused(error) or error.status >= 500 or error.status == 429:
                raise
            if error.status in CLAIM_LOST:
                log.warning("report %s waits for a later claim of its item", entry.key)
                self.journal.lapse(entry.key)
                return Sent.LAPSED
            log.error("report %s refused and set aside: %s", entry.key, error)
            self.journal.set_aside(entry.key)
            return Sent.SET_ASIDE
        self.journal.sent(entry.key)
        return Sent.RECORDED

    async def _calling[T](self, call: Callable[[ApiClient], Awaitable[T]]) -> T:
        """One call with the credential as it is now. A refusal of the
        credential marks it refused before it is raised."""
        try:
            async with self.enrollment.client() as client:
                return await call(client)
        except ApiError as error:
            if refused(error):
                self.enrollment.refuse()
            raise
