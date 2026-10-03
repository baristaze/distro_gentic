from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agents.gate import ResultGateInterface
from acme.om.agents.types.result import Result
from acme.om.base import Identifiable, Platform, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.evidence.acceptance import Chain, evidence_text, judge_chain, scenario_refusal
from acme.om.evidence.collector import collect, digest
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.harness import AcceptanceHarnessInterface
from acme.om.evidence.rules import compatibility_refusal, scan
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.acceptance import AcceptanceVerdict, Break, Link, Scenario, Surface
from acme.om.evidence.types.record import ExecutionRecord, RunPurpose
from acme.om.evidence.types.validation import Delivery, ExecutionRequest
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import ValidationFailed

PAGE = 500
"""Rows one read of the session's runs, or its inferences, takes."""


class AcceptanceOptions(Platform):
    max_validations: int = 100  # validations and baselines of one session the harness reads
    max_runs: int = 100_000  # runs of those it reads
    max_inferences: int = 10_000  # hypotheses and findings it reads


class AcceptanceHarnessImpl(AcceptanceHarnessInterface):
    """Reads the chain from the evidence's storage and the work product's
    system, never from what the session says of it; asks the gate again;
    runs the hidden suite on the executor; and judges (`acceptance`). What
    it cannot read in full is a break, never a pass."""

    def __init__(
        self,
        storage: EvidenceStorageInterface,
        work_product: WorkProductInterface,
        executor: ExecutorInterface,
        gate: ResultGateInterface,
        options: AcceptanceOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._work_product = work_product
        self._executor = executor
        self._gate = gate
        self._options = options or AcceptanceOptions()
        self._clock = clock

    async def judge(
        self,
        ctx: TenantContext,
        scenario: Scenario,
        session_id: UUID,
        result: Result,
        surfaces: Mapping[Surface, Mapping[str, str]],
    ) -> AcceptanceVerdict:
        ctx.require(Permission.READ)
        refusal = scenario_refusal(scenario)
        if refusal is not None:
            raise ValidationFailed(f"scenario {scenario.name}: {refusal}")
        # The harness reads the session's evidence itself; every other surface
        # is named by the caller, and one left out is refused, never clean.
        missing = sorted(set(Surface) - {Surface.EVIDENCE} - set(surfaces))
        if missing:
            raise ValidationFailed(
                f"a scan covers every surface the agent reads; missing: {[s.value for s in missing]}"
            )
        verdict_id, now = new_id(), self._clock()
        verdict = await self._gate.check(ctx, session_id, result)
        delivery = await self._work_product.delivered(ctx, session_id)
        bound = self._options.max_validations
        validations = tuple(
            await self._storage.read_validations(ctx.org_id, session_id, None, bound + 1)
        )
        # Every run of the session, the agent's own beside the executor's:
        # the chain is judged from the executor's, and the scan reads them all.
        records = await _paged(
            lambda after: self._storage.read_records(ctx.org_id, session_id, after, PAGE),
            self._options.max_runs,
        )
        inferences = await _paged(
            lambda after: self._storage.read_inferences(ctx.org_id, session_id, after, PAGE),
            self._options.max_inferences,
        )
        unread: list[Break] = []
        if len(validations) > bound or len(records) > self._options.max_runs:
            unread.append(Break(link=Link.BASELINE, reason="more runs than the harness reads"))
        if len(inferences) > self._options.max_inferences:
            unread.append(Break(link=Link.HYPOTHESES, reason="more inferences than it reads"))
        hidden, hidden_break = await self._hidden(ctx, scenario, session_id, delivery, verdict_id)
        read = {surface: dict(items) for surface, items in surfaces.items()}
        read[Surface.PROMPT]["objective"] = scenario.objective
        evidence = read.setdefault(Surface.EVIDENCE, {})
        evidence |= evidence_text(validations, records, inferences)
        chain = Chain(
            delivery=delivery,
            validations=validations,
            records=records,
            inferences=inferences,
            result=result,
            verdict=verdict,
            hidden=hidden,
            leaks=scan(scenario.hidden.markers, read),
        )
        breaks = (*unread, *judge_chain(scenario, chain), *hidden_break)
        return AcceptanceVerdict(
            id=verdict_id,
            created_at=now,
            scenario=scenario.name,
            session_id=session_id,
            head=delivery.head if delivery is not None else None,
            breaks=breaks,
            hidden=hidden,
        )

    async def _hidden(
        self,
        ctx: TenantContext,
        scenario: Scenario,
        session_id: UUID,
        delivery: Delivery | None,
        verdict_id: UUID,
    ) -> tuple[tuple[ExecutionRecord, ...], tuple[Break, ...]]:
        """The hidden suite at the head, on a fresh executor, from its own
        source, which no workspace holds: the executor fetches it for this
        run alone. Its runs belong to the verdict: none is stored where the
        session's evidence is."""
        if delivery is None:
            return (), ()
        offer = await self._executor.offer(ctx)
        for check in scenario.hidden.checks:
            refusal = compatibility_refusal(check, offer)
            if refusal is not None:
                return (), (Break(link=Link.HIDDEN, reason=refusal),)
        request = ExecutionRequest(
            session_id=session_id,
            project=scenario.project,
            purpose=RunPurpose.VALIDATION,
            version=delivery.head,
            source=scenario.hidden.source,
            checks=scenario.hidden.checks,
            trials=(1,) * len(scenario.hidden.checks),
        )
        report = await self._executor.run(ctx, request)
        if digest(report.results) != report.sha256:
            reason = "the hidden suite's results do not hash to what the executor wrote"
            return (), (Break(link=Link.HIDDEN, reason=reason),)
        try:
            records = collect(
                report.results,
                executor=report.executor,
                session_id=session_id,
                project=scenario.project,
                purpose=RunPurpose.VALIDATION,
                validation_id=verdict_id,
                now=self._clock(),
            )
        except ValidationFailed as refused:
            return (), (Break(link=Link.HIDDEN, reason=refused.message),)
        return records, ()


async def _paged[T: Identifiable](
    read: Callable[[UUID | None], Awaitable[Sequence[T]]], bound: int
) -> tuple[T, ...]:
    """Every row a paged read answers, oldest first, until one more than
    `bound` is in hand: a caller that finds more than `bound` read too many."""
    found: list[T] = []
    after: UUID | None = None
    while len(found) <= bound:
        page = await read(after)
        found.extend(page)
        if len(page) < PAGE:
            break
        after = page[-1].id
    return tuple(found)
