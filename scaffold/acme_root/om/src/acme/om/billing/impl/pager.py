import logging

from acme.infra.observability import OUTCOMES
from acme.om.billing.pager import AnomalyPage, OperatorPagerInterface

log = logging.getLogger(__name__)


class OperatorPagerLogImpl(OperatorPagerInterface):
    """The page as an error the operators' alerting reads: one log line at
    error, and the `billing` `paged` outcome counted, naming the tenant,
    the session, and the figures, never the session's content."""

    async def page(self, page: AnomalyPage) -> None:
        log.error(
            "anomaly in org %s, session %s: expected %d micros against a norm of %d",
            page.org_id,
            page.session_id,
            page.expected_micros,
            page.norm_micros,
        )
        OUTCOMES.labels(subsystem="billing", outcome="paged").inc()

    def describe(self) -> str:
        return "pager=log"


class OperatorPagerMemoryImpl(OperatorPagerInterface):
    """Keeps every page, for a test to read."""

    def __init__(self) -> None:
        self.pages: list[AnomalyPage] = []

    async def page(self, page: AnomalyPage) -> None:
        self.pages.append(page)

    def describe(self) -> str:
        return "pager=memory"
