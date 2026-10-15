"""The `handoff` toolset: hand engineering work to a new software engineer
session, which starts when its person confirms it."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from pydantic import Field

from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.request import MAX_TITLE, Handoff
from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.platform_agents import kinds
from acme.om.platform_agents.tools.base import NativeToolImpl
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec


class HandOffInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str = Field(min_length=1, max_length=20_000)


class HandedOff(OmBase):
    agent_session_id: UUID
    note: str


class HandOffToSoftwareEngineerImpl(NativeToolImpl):
    """Hands engineering work to a new software engineer session. Its objective is
    data there, it waits for its person to confirm it, and the session that
    handed it over cannot steer it. The new session's id is the call's own,
    so a call asked again finds the session it made."""

    SPEC = ToolSpec(
        name=kinds.HAND_OFF,
        description=(
            "Hands engineering work to a new software engineer session, with a title and an objective "
            "that stands on its own: what to change, why, and how to know it is done. The "
            "session starts when its person confirms it; you cannot steer it after."
        ),
        input_model=HandOffInput,
        output_model=HandedOff,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.SPAWN,
        effect=Effect.IDEMPOTENT,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agents: Callable[[], AgentsManagerInterface]) -> None:
        self._agents = agents

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, HandOffInput)
        handoff = Handoff(
            id=runtime.key,
            kind=kinds.SOFTWARE_ENGINEER,
            title=call_input.title,
            objective=call_input.objective,
        )
        session = await self._agents().hand_off(ctx, runtime.agent_session_id, handoff)
        return HandedOff(
            agent_session_id=session.id, note="It starts when its person confirms the objective."
        )
