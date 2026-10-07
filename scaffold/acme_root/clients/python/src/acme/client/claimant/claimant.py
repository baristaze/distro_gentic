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
order, and the outcomes are the same."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from acme.client.claimant.backoff import Backoff
from acme.client.claimant.enrollment import (
    ClientFactory,
    CredentialRefused,
    Enrollment,
    RoutesClaimantImpl,
    refused,
)
from acme.client.claimant.journal import Entry, Journal
from acme.client.claimant.settings import ClaimantSettings
from acme.client.client import WIRE_FAILURES, ApiClient, ApiError
from acme.client.types import ClaimantWorkView, ReportOutcome

log = logging.getLogger(__name__)

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
        self._backoff = Backoff(jitter) if jitter is not None else Backoff()

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
            return Turn(None, self._backoff.failed(error.retry_after))
        except WIRE_FAILURES as error:
            log.warning("the platform is unreachable: %s", error)
            return Turn(None, self._backoff.failed(None))
        self._backoff.reset()
        return Turn(item, 0.0 if item is not None else self._settings.beat_seconds)

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
        and the next turn sends it.

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
        return await self.keep(Entry(str(item.id), str(item.id), body))

    async def keep(self, entry: Entry) -> bool:
        """Keeps a report in the journal, then sends it with `send`:
        whether the platform recorded it."""
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
