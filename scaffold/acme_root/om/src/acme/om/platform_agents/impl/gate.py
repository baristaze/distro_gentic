"""The gate a review passes: a result of a reviewer's session is judged by
the reads and the findings it cites, read from the session's own history,
and every other result passes the gate it passed before, unchanged."""

from collections.abc import Collection
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.header import ToolRequestHeader, ToolResponseHeader
from acme.om.agents.gate import ResultGateInterface
from acme.om.agents.types.result import Result, Verdict
from acme.om.base import OmBase
from acme.om.context import Permission, TenantContext
from acme.om.platform_agents import kinds, rules

REVIEWING: frozenset[str] = frozenset({kinds.REVIEWER})
"""The kinds whose results are reviews, by name, at every version."""


class ReviewGateOptions(OmBase):
    max_cited: int = 500  # ids one review may cite
    max_steps: int = 20_000  # steps of the session's history the gate reads, at most
    page: int = 200  # steps one read of the history takes


class ResultGateReviewImpl(ResultGateInterface):
    """A review's result names the calls of its own session that show it:
    the read of the pull request, and each finding noted. The gate reads the
    session's history, a page at a time, for those calls and their answers,
    and judges them (`rules.review_verdict`); a history past what it reads
    is refused, never judged on part of it. A session of any other kind
    passes `inner`."""

    def __init__(
        self,
        inner: ResultGateInterface,
        sessions: AgentSessionsManagerInterface,
        steps: AgentStepsManagerInterface,
        options: ReviewGateOptions | None = None,
    ) -> None:
        self._inner = inner
        self._sessions = sessions
        self._steps = steps
        self._options = options or ReviewGateOptions()

    async def check(self, ctx: TenantContext, agent_session_id: UUID, result: Result) -> Verdict:
        ctx.require(Permission.READ)
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        if session.kind not in REVIEWING:
            return await self._inner.check(ctx, agent_session_id, result)
        cited = set(result.evidence)
        if len(cited) > self._options.max_cited:
            return Verdict(
                accepted=False,
                reason=f"a review cites at most {self._options.max_cited} reads and findings",
            )
        calls = await self._calls(ctx, agent_session_id, cited)
        if calls is None:
            return Verdict(
                accepted=False,
                reason=f"the session's history is past the {self._options.max_steps} steps "
                "the gate reads, so no review counts",
            )
        return rules.review_verdict(result.claim, cited, calls)

    async def _calls(
        self, ctx: TenantContext, agent_session_id: UUID, cited: Collection[UUID]
    ) -> dict[UUID, rules.Call] | None:
        """The calls `cited` names, each with its answer, as the history
        holds them; None when the history runs past what the gate reads."""
        calls: dict[UUID, rules.Call] = {}
        after, read = 0, 0
        while True:
            page = await self._steps.get_agent_steps(
                ctx, agent_session_id, after, self._options.page
            )
            for step in page.items:
                header = step.header
                if step.id in cited and isinstance(header, ToolRequestHeader):
                    calls[step.id] = rules.Call(tool=header.tool)
                asked = step.responds_to
                if asked is not None and asked in calls and isinstance(header, ToolResponseHeader):
                    calls[asked] = calls[asked]._replace(answered=True, failure=header.failure)
            read += len(page.items)
            if not page.has_more or not page.items:
                return calls
            if read >= self._options.max_steps:
                return None
            after = page.items[-1].seq
