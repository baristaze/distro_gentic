"""How billing reaches the operator: a page about a call the anomaly guard
parked. What carries it is the root's choice."""

from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform


class AnomalyPage(Platform):
    """A call far above its session's norm, parked for a person. It names
    the session and the figures, never the session's content."""

    org_id: UUID
    session_id: UUID | None
    expected_micros: int = Field(ge=0)
    norm_micros: int = Field(ge=0)


class OperatorPagerInterface(ABC):
    @abstractmethod
    async def page(self, page: AnomalyPage) -> None:
        """Raises the page. A pager that cannot reach its carrier logs the
        failure and returns: the call stays parked either way."""
        ...

    @abstractmethod
    def describe(self) -> str: ...
