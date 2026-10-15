"""What several of the shipped tools share: the tool of the platform's own
code they all extend, the bounds and patterns their inputs hold, and the
inputs and outputs more than one toolset takes."""

from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.agents.types.result import Claim
from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import Target
from acme.om.tools.types.tool import ToolInput, ToolSpec

MAX_PATH = 1024
MAX_READ = 200_000  # bytes one read takes at most
NO_NUL = r"^[^\x00]*$"
# A line break splits grep's pattern into several, any of which matches, and
# an empty one matches every line: a search's pattern is one line.
ONE_LINE = r"^[^\x00\r\n]*$"
LIST_MAX = 50  # rows one list answers at most
HOSTS_MAX = 20  # a pool's hosts read_wait answers at most


class NativeToolImpl(ToolInterface):
    """A tool of the platform's own code: it acts on nothing a target names,
    and has nothing to refuse before a person is asked."""

    SPEC: ClassVar[ToolSpec]

    @property
    def spec(self) -> ToolSpec:
        return self.SPEC

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        return Target()

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        return None


class Text(OmBase):
    text: str


class ResultInput(ToolInput):
    claim: Claim
    evidence: tuple[UUID, ...] = ()


class PageInput(ToolInput):
    after: UUID | None = None  # the `next` an earlier answer gave
    limit: int = Field(default=20, ge=1, le=LIST_MAX)
